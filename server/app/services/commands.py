from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import CommandMessage, CommandSource, CommandType

ALLOWED_COMMANDS: set[str] = {
    "window.open",
    "window.close",
    "alarm.on",
    "alarm.off",
    "led.on",
    "led.off",
    "control.set_priority",
    "control.resume_auto",
    "alarm.silence",
    "voice.speak",
    "display.message",
}


def validate_command_type(raw: str) -> CommandType:
    if raw in ALLOWED_COMMANDS:
        return raw  # type: ignore[return-value]
    raise ValueError(f"unsupported command type: {raw}")


def ensure_device(db: Session, device_id: str) -> models.Device:
    device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
    if device:
        return device
    device = models.Device(device_id=device_id, display_name=device_id, status="unknown")
    db.add(device)
    try:
        db.flush()
    except IntegrityError:
        # 新设备首次上线时，MQTT 接入线程和 HTTP 请求可能并发插入同一 device_id
        db.rollback()
        device = db.query(models.Device).filter(models.Device.device_id == device_id).one()
    return device


def create_command(
    db: Session,
    device_id: str,
    command_type: str,
    *,
    parameter: dict[str, Any] | None = None,
    source: CommandSource = "frontend",
    confidence: float = 0.0,
    reason: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> models.Command:
    ensure_device(db, device_id)
    message = CommandMessage(
        type=validate_command_type(command_type),
        parameter=parameter or {},
        source=source,
        confidence=max(0.0, min(1.0, confidence)),
        reason=reason,
    )
    command = models.Command(
        command_id=message.command_id,
        device_id=device_id,
        type=message.type,
        parameter=message.parameter,
        source=message.source,
        confidence=message.confidence,
        reason=message.reason,
        status="pending",
        raw_payload=raw_payload or message.model_dump(mode="json"),
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def mark_published(db: Session, command: models.Command) -> models.Command:
    # 设备的 command_ack 可能已由 MQTT 接入线程先行落库（status=executed），
    # 因此只在仍为 pending 时推进到 published，避免把 ack 结果覆盖回去。
    db.execute(
        update(models.Command)
        .where(models.Command.command_id == command.command_id)
        .values(
            published_at=datetime.now(UTC).replace(tzinfo=None),
            status=case(
                (models.Command.status == "pending", "published"),
                else_=models.Command.status,
            ),
        )
    )
    db.commit()
    db.refresh(command)
    return command


def serialize_command(command: models.Command) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "type": command.type,
        "parameter": command.parameter or {},
        "source": command.source,
        "confidence": command.confidence or 0.0,
        "reason": command.reason or "",
        "status": command.status,
        "created_at": iso_utc(command.created_at) if command.created_at else "",
        "published_at": iso_utc(command.published_at),
        "executed_at": iso_utc(command.executed_at),
    }
