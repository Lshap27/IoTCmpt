from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.schemas import CommandMessage, CommandSource, CommandType

ALLOWED_COMMANDS: set[str] = {
    "none",
    "window.open",
    "window.close",
    "alarm.on",
    "alarm.off",
    "display.message",
}


def validate_command_type(raw: str) -> CommandType:
    if raw in ALLOWED_COMMANDS:
        return raw  # type: ignore[return-value]
    return "none"


def ensure_device(db: Session, device_id: str) -> models.Device:
    device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
    if device:
        return device
    device = models.Device(device_id=device_id, display_name=device_id, status="unknown")
    db.add(device)
    db.flush()
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
    command.status = "published"
    command.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(command)
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
        "created_at": command.created_at.isoformat() if command.created_at else "",
    }

