from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import WebSocketEnvelope
from app.services.commands import create_command, mark_published, serialize_command
from app.services.llm import LLMService
from app.services.mqtt import MqttGateway
from app.services.pose import latest_pose_result, serialize_pose_result
from app.services.telemetry import serialize_telemetry
from app.services.websocket import manager


def latest_image_asset(db: Session, device_id: str) -> models.ImageAsset | None:
    return (
        db.query(models.ImageAsset)
        .filter(models.ImageAsset.device_id == device_id)
        .filter(models.ImageAsset.kind == "capture")
        .order_by(models.ImageAsset.created_at.desc())
        .first()
    )


def resolve_recent_image(settings: Settings, asset: models.ImageAsset | None) -> Path | None:
    """返回可以喂给视觉模型的本地图片路径；图片过期、缺失或视觉关闭时返回 None。"""
    if asset is None or not settings.llm_vision_enabled:
        return None
    if asset.created_at is None:
        return None
    age = datetime.now(UTC).replace(tzinfo=None) - asset.created_at
    if age.total_seconds() > settings.llm_image_max_age_seconds:
        return None
    path = Path(settings.uploads_dir) / asset.device_id / asset.filename
    if not path.is_file():
        return None
    return path


def collect_device_snapshot(db: Session, device_id: str, *, include_trend: bool = False) -> dict[str, Any]:
    device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
    telemetry = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id)
        .order_by(models.Telemetry.sampled_at.desc())
        .first()
    )
    image = latest_image_asset(db, device_id)
    command = (
        db.query(models.Command)
        .filter(models.Command.device_id == device_id)
        .order_by(models.Command.created_at.desc())
        .first()
    )
    ai_result = (
        db.query(models.AiResult)
        .filter(models.AiResult.device_id == device_id)
        .order_by(models.AiResult.created_at.desc())
        .first()
    )
    pose = latest_pose_result(db, device_id)

    snapshot: dict[str, Any] = {
        "device": {
            "device_id": device_id,
            "display_name": device.display_name if device else device_id,
            "status": device.status if device else "unknown",
            "last_seen_at": iso_utc(device.last_seen_at) if device else None,
        },
        "telemetry": serialize_telemetry(telemetry) if telemetry else None,
        "image": {"id": image.id, "url": image.url, "created_at": iso_utc(image.created_at)} if image else None,
        "pose": serialize_pose_result(db, pose) if pose else None,
        "command": serialize_command(command) if command else None,
        "ai_result": {
            "command_id": ai_result.command_id,
            "risk_level": ai_result.risk_level,
            "confidence": ai_result.confidence,
            "reason": ai_result.reason,
            "summary": ai_result.summary,
            "model": ai_result.model,
        }
        if ai_result
        else None,
    }

    if include_trend:
        rows = (
            db.query(models.Telemetry)
            .filter(models.Telemetry.device_id == device_id)
            .order_by(models.Telemetry.sampled_at.desc())
            .limit(10)
            .all()
        )
        snapshot["trend"] = [
            {
                "sampled_at": row.sampled_at.isoformat(timespec="seconds"),
                "temperature_c": row.temperature_c,
                "humidity_percent": row.humidity_percent,
                "tvoc_ppb": row.tvoc_ppb,
                "eco2_ppm": row.eco2_ppm,
                "air_quality": row.air_quality,
                "smoke_detected": row.smoke_detected,
                "led_on": row.led_on,
            }
            for row in reversed(rows)
        ]

    return snapshot


async def run_ai_analysis(
    db: Session,
    device_id: str,
    llm: LLMService,
    mqtt_service: MqttGateway | None,
    *,
    trigger: str = "manual",
) -> dict[str, Any]:
    """完整分析管线：广播分析中 -> LLM 决策(可带图) -> 落库 -> 置信度门槛决定是否下发 -> 广播结果。

    DB 查询/提交都是同步阻塞调用，必须借 asyncio.to_thread 移出事件循环，
    否则 Postgres 卡顿时整个网关（WS/HTTP/MQTT）都会跟着冻结。
    已广播 ai_analyzing 后无论成败都必须再广播一个终态（ai_result / ai_error），
    否则前端的"分析中"状态会永远悬着。
    """
    settings = get_settings()
    await manager.broadcast(
        device_id,
        WebSocketEnvelope(type="ai_analyzing", device_id=device_id, payload={"trigger": trigger}).model_dump(
            mode="json"
        ),
    )

    try:
        def _collect() -> tuple[dict[str, Any], Path | None]:
            snapshot = collect_device_snapshot(db, device_id, include_trend=True)
            image_path = resolve_recent_image(settings, latest_image_asset(db, device_id))
            return snapshot, image_path

        snapshot, image_path = await asyncio.to_thread(_collect)
        decision = await llm.analyze(snapshot, image_path=image_path)
        message = decision.command

        def _persist() -> tuple[models.Command, models.AiResult]:
            command = create_command(
                db,
                device_id,
                message.type,
                parameter=message.parameter,
                source="llm",
                confidence=message.confidence,
                reason=message.reason,
                raw_payload={"trigger": trigger, "decision": decision.model_dump(mode="json")},
            )
            ai_result = models.AiResult(
                device_id=device_id,
                command_id=command.command_id,
                summary=decision.summary or message.reason,
                risk_level=decision.risk_level,
                model=decision.model or settings.llm_model,
                confidence=message.confidence,
                reason=message.reason,
                raw_payload={
                    "trigger": trigger,
                    "decision": decision.model_dump(mode="json"),
                    "image_attached": image_path is not None,
                },
            )
            db.add(ai_result)
            db.commit()
            return command, ai_result

        command, ai_result = await asyncio.to_thread(_persist)

        published = False
        if (
            message.type != "none"
            and message.confidence >= settings.autopilot_min_confidence
            and mqtt_service is not None
        ):
            published = await mqtt_service.publish_json(
                f"devices/{device_id}/command", serialize_command(command), qos=1
            )
            if published:
                await asyncio.to_thread(mark_published, db, command)

        payload = {
            "command": serialize_command(command),
            "risk_level": decision.risk_level,
            "confidence": message.confidence,
            "reason": message.reason,
            "model": ai_result.model,
            "trigger": trigger,
            "published": published,
            "image_attached": image_path is not None,
        }
    except Exception:
        await manager.broadcast(
            device_id,
            WebSocketEnvelope(
                type="ai_error",
                device_id=device_id,
                payload={"trigger": trigger, "message": "AI 分析失败，请稍后重试"},
            ).model_dump(mode="json"),
        )
        raise

    await manager.broadcast(
        device_id,
        WebSocketEnvelope(type="ai_result", device_id=device_id, payload=payload).model_dump(mode="json"),
    )
    return payload
