from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.services.commands import ensure_device

MAX_DEMO_SAMPLES = 10_000
MIN_INTERVAL_SECONDS = 2.5
MAX_INTERVAL_SECONDS = 3600.0
DATA_CATEGORIES = {"telemetry", "events", "ai", "notifications"}


class DataToolError(ValueError):
    pass


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DataToolError(f"{label}必须是带时区的 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise DataToolError(f"{label}必须包含时区偏移")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def parse_time_range(start_at: Any, end_at: Any) -> tuple[datetime, datetime]:
    start = _parse_timestamp(start_at, "开始时间")
    end = _parse_timestamp(end_at, "结束时间")
    if start >= end:
        raise DataToolError("结束时间必须晚于开始时间")
    return start, end


def _validate_device_id(device_id: Any) -> str:
    value = str(device_id or "").strip()
    if not value or len(value) > 64 or not all(char.isalnum() or char in "._-" for char in value):
        raise DataToolError("设备 ID 必须为 1-64 位，只能包含字母、数字、点、下划线和连字符")
    return value


def _count_range(db: Session, model: type[Any], column: Any, device_id: str, start: datetime, end: datetime) -> int:
    return int(db.query(model).filter(model.device_id == device_id, column >= start, column < end).count())


def preview_data(db: Session, device_id: Any, start_at: Any, end_at: Any) -> dict[str, Any]:
    device = _validate_device_id(device_id)
    start, end = parse_time_range(start_at, end_at)
    command_count = _count_range(db, models.Command, models.Command.created_at, device, start, end)
    ai_result_count = _count_range(db, models.AiResult, models.AiResult.created_at, device, start, end)
    counts = {
        "telemetry": _count_range(db, models.Telemetry, models.Telemetry.sampled_at, device, start, end),
        "events": _count_range(db, models.DeviceEvent, models.DeviceEvent.created_at, device, start, end),
        "ai": command_count + ai_result_count,
        "commands": command_count,
        "aiResults": ai_result_count,
        "notifications": _count_range(db, models.Notification, models.Notification.created_at, device, start, end),
    }
    return {
        "deviceId": device,
        "startAt": iso_utc(start),
        "endAt": iso_utc(end),
        "counts": counts,
    }


def cleanup_data(
    db: Session,
    device_id: Any,
    start_at: Any,
    end_at: Any,
    categories: Any,
) -> dict[str, Any]:
    device = _validate_device_id(device_id)
    start, end = parse_time_range(start_at, end_at)
    selected = list(dict.fromkeys(str(item) for item in (categories or [])))
    if not selected:
        raise DataToolError("请至少选择一种要清理的数据")
    unknown = set(selected) - DATA_CATEGORIES
    if unknown:
        raise DataToolError(f"不支持的数据类别：{sorted(unknown)}")

    deleted = {"telemetry": 0, "events": 0, "ai": 0, "commands": 0, "aiResults": 0, "notifications": 0}
    try:
        if "telemetry" in selected:
            deleted["telemetry"] = (
                db.query(models.Telemetry)
                .filter(
                    models.Telemetry.device_id == device,
                    models.Telemetry.sampled_at >= start,
                    models.Telemetry.sampled_at < end,
                )
                .delete(synchronize_session=False)
            )
        if "events" in selected:
            deleted["events"] = (
                db.query(models.DeviceEvent)
                .filter(
                    models.DeviceEvent.device_id == device,
                    models.DeviceEvent.created_at >= start,
                    models.DeviceEvent.created_at < end,
                )
                .delete(synchronize_session=False)
            )
        if "ai" in selected:
            deleted["aiResults"] = (
                db.query(models.AiResult)
                .filter(
                    models.AiResult.device_id == device,
                    models.AiResult.created_at >= start,
                    models.AiResult.created_at < end,
                )
                .delete(synchronize_session=False)
            )
            deleted["commands"] = (
                db.query(models.Command)
                .filter(
                    models.Command.device_id == device,
                    models.Command.created_at >= start,
                    models.Command.created_at < end,
                )
                .delete(synchronize_session=False)
            )
            deleted["ai"] = deleted["aiResults"] + deleted["commands"]
        if "notifications" in selected:
            deleted["notifications"] = (
                db.query(models.Notification)
                .filter(
                    models.Notification.device_id == device,
                    models.Notification.created_at >= start,
                    models.Notification.created_at < end,
                )
                .delete(synchronize_session=False)
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "ok": True,
        "deviceId": device,
        "startAt": iso_utc(start),
        "endAt": iso_utc(end),
        "deleted": deleted,
    }


STAGES = (
    ("normal", "正常环境", "info"),
    ("watch", "空气质量需要关注", "warning"),
    ("alert", "空气质量告警", "warning"),
    ("smoke", "检测到烟雾并触发本地报警", "critical"),
    ("recovery", "告警解除，环境逐步恢复", "info"),
)


def _stage_values(stage: str, progress: float, sample_index: int) -> dict[str, Any]:
    wave = ((sample_index % 11) - 5) / 10
    if stage == "normal":
        return {
            "temperature_c": 24.0 + wave * 0.4,
            "humidity_percent": 48.0 + wave * 2,
            "tvoc_ppb": 80.0 + wave * 10,
            "hcho_ug_m3": 22.0 + wave * 2,
            "eco2_ppm": 620.0 + wave * 30,
            "light_is_dark": False,
            "smoke_detected": False,
            "window_open": False,
            "alarm_on": False,
            "led_on": False,
            "air_quality": "good",
            "recommend_open_window": False,
            "alarm_enabled": False,
            "reason": "演示阶段：环境正常",
        }
    if stage == "watch":
        return {
            "temperature_c": 25.0 + progress,
            "humidity_percent": 55.0 + progress * 8,
            "tvoc_ppb": 220.0 + progress * 220,
            "hcho_ug_m3": 45.0 + progress * 30,
            "eco2_ppm": 820.0 + progress * 280,
            "light_is_dark": True,
            "smoke_detected": False,
            "window_open": False,
            "alarm_on": False,
            "led_on": True,
            "air_quality": "watch",
            "recommend_open_window": False,
            "alarm_enabled": True,
            "reason": "演示阶段：污染指标正在上升",
        }
    if stage == "alert":
        return {
            "temperature_c": 27.0 + progress * 1.5,
            "humidity_percent": 66.0 + progress * 6,
            "tvoc_ppb": 650.0 + progress * 350,
            "hcho_ug_m3": 90.0 + progress * 45,
            "eco2_ppm": 1250.0 + progress * 650,
            "light_is_dark": True,
            "smoke_detected": False,
            "window_open": progress >= 0.35,
            "alarm_on": False,
            "led_on": True,
            "air_quality": "alert",
            "recommend_open_window": True,
            "alarm_enabled": True,
            "reason": "演示阶段：空气质量告警，建议通风",
        }
    if stage == "smoke":
        return {
            "temperature_c": 29.0 + progress,
            "humidity_percent": 70.0 - progress * 3,
            "tvoc_ppb": 1100.0 + progress * 300,
            "hcho_ug_m3": 140.0 + progress * 30,
            "eco2_ppm": 1900.0 + progress * 300,
            "light_is_dark": True,
            "smoke_detected": True,
            "window_open": True,
            "alarm_on": True,
            "led_on": True,
            "air_quality": "alert",
            "recommend_open_window": True,
            "alarm_enabled": True,
            "reason": "演示阶段：MQ-2 检测到烟雾",
        }
    return {
        "temperature_c": 28.0 - progress * 3.5,
        "humidity_percent": 65.0 - progress * 13,
        "tvoc_ppb": 800.0 - progress * 680,
        "hcho_ug_m3": 100.0 - progress * 72,
        "eco2_ppm": 1500.0 - progress * 780,
        "light_is_dark": False,
        "smoke_detected": False,
        "window_open": progress < 0.75,
        "alarm_on": False,
        "led_on": progress < 0.5,
        "air_quality": "good" if progress >= 0.5 else "watch",
        "recommend_open_window": progress < 0.5,
        "alarm_enabled": True,
        "reason": "演示阶段：告警解除，环境恢复中",
    }


def _telemetry_mapping(device_id: str, sampled_at: datetime, values: dict[str, Any]) -> dict[str, Any]:
    sensors = {
        key: values[key]
        for key in (
            "temperature_c",
            "humidity_percent",
            "tvoc_ppb",
            "hcho_ug_m3",
            "eco2_ppm",
            "light_is_dark",
            "smoke_detected",
        )
    }
    state = {
        "window_open": values["window_open"],
        "alarm_on": values["alarm_on"],
        "manual_override": False,
        "manual_window_override": False,
        "manual_led_override": False,
        "control_priority": "manual_first",
        "smoke_silenced": False,
        "led_on": values["led_on"],
    }
    fusion = {key: values[key] for key in ("air_quality", "recommend_open_window", "alarm_enabled", "reason")}
    return {
        "device_id": device_id,
        "sampled_at": sampled_at,
        **sensors,
        **state,
        **fusion,
        "raw_payload": {
            "device_id": device_id,
            "sampled_at": iso_utc(sampled_at),
            "sensors": sensors,
            "state": state,
            "fusion": fusion,
        },
        "created_at": sampled_at,
    }


def generate_demo_data(
    db: Session,
    device_id: Any,
    start_at: Any,
    end_at: Any,
    interval_seconds: Any = 60,
) -> dict[str, Any]:
    device = _validate_device_id(device_id)
    start, end = parse_time_range(start_at, end_at)
    try:
        interval = float(interval_seconds)
    except (TypeError, ValueError) as exc:
        raise DataToolError("采样间隔必须是数字") from exc
    if not MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
        raise DataToolError("采样间隔必须在 2.5 到 3600 秒之间")
    sample_count = math.ceil((end - start).total_seconds() / interval)
    if sample_count < len(STAGES):
        raise DataToolError("目标时段至少需要容纳 5 条采样，才能覆盖全部演示阶段")
    if sample_count > MAX_DEMO_SAMPLES:
        raise DataToolError("预计生成超过 10000 条，请缩短时间范围或增大采样间隔")

    telemetry_rows: list[dict[str, Any]] = []
    stage_first_seen: dict[str, datetime] = {}
    for index in range(sample_count):
        sampled_at = start + timedelta(seconds=index * interval)
        stage_index = min(len(STAGES) - 1, index * len(STAGES) // sample_count)
        stage = STAGES[stage_index][0]
        stage_start_index = math.ceil(stage_index * sample_count / len(STAGES))
        stage_end_index = math.ceil((stage_index + 1) * sample_count / len(STAGES))
        stage_size = max(1, stage_end_index - stage_start_index)
        progress = min(1.0, max(0.0, (index - stage_start_index) / max(1, stage_size - 1)))
        stage_first_seen.setdefault(stage, sampled_at)
        telemetry_rows.append(_telemetry_mapping(device, sampled_at, _stage_values(stage, progress, index)))

    event_types = {
        "normal": "demo.stage.normal",
        "watch": "air.quality.watch",
        "alert": "air.quality.alert",
        "smoke": "smoke.detected",
        "recovery": "smoke.cleared",
    }
    event_rows = [
        {
            "device_id": device,
            "type": event_types[stage],
            "severity": severity,
            "message": message,
            "raw_payload": {"type": event_types[stage], "demo": True, "stage": stage},
            "created_at": stage_first_seen[stage],
        }
        for stage, message, severity in STAGES
    ]

    try:
        ensure_device(db, device)
        db.query(models.Telemetry).filter(
            models.Telemetry.device_id == device,
            models.Telemetry.sampled_at >= start,
            models.Telemetry.sampled_at < end,
        ).delete(synchronize_session=False)
        db.query(models.DeviceEvent).filter(
            models.DeviceEvent.device_id == device,
            models.DeviceEvent.created_at >= start,
            models.DeviceEvent.created_at < end,
        ).delete(synchronize_session=False)
        db.bulk_insert_mappings(models.Telemetry, telemetry_rows)
        db.bulk_insert_mappings(models.DeviceEvent, event_rows)
        stored_device = db.query(models.Device).filter(models.Device.device_id == device).one()
        last_sampled_at = telemetry_rows[-1]["sampled_at"]
        if stored_device.last_seen_at is None or stored_device.last_seen_at < last_sampled_at:
            stored_device.last_seen_at = last_sampled_at
        db.add(stored_device)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "deviceId": device,
        "startAt": iso_utc(start),
        "endAt": iso_utc(end),
        "intervalSeconds": interval,
        "generated": {"telemetry": sample_count, "events": len(event_rows)},
        "stages": [stage for stage, _message, _severity in STAGES],
    }


def run_operation(db: Session, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    common = (payload.get("deviceId"), payload.get("startAt"), payload.get("endAt"))
    if operation == "preview":
        return preview_data(db, *common)
    if operation == "cleanup":
        return cleanup_data(db, *common, payload.get("categories"))
    if operation == "demo":
        return generate_demo_data(db, *common, payload.get("intervalSeconds", 60))
    raise DataToolError(f"未知数据工具操作：{operation}")


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"detail": "usage: python -m app.tools.data_manager <preview|cleanup|demo>"}))
        return 2
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise DataToolError("请求体必须是 JSON 对象")
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            result = run_operation(db, sys.argv[1], payload)
        finally:
            db.close()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DataToolError, json.JSONDecodeError) as exc:
        print(json.dumps({"detail": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"detail": f"数据操作失败：{exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
