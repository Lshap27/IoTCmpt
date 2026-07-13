from __future__ import annotations

import base64
from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import NotificationIn, VoiceStatus
from app.services.commands import create_command, ensure_device


def voice_status(command: models.Command | None, requested: bool) -> VoiceStatus:
    if not requested:
        return "not_requested"
    if command is None or (command.status == "pending" and command.published_at is None):
        return "unavailable"
    if command.status in {"executed", "rejected", "failed"}:
        return command.status  # type: ignore[return-value]
    return "pending"


def serialize_notification(
    db: Session,
    notification: models.Notification,
    commands: Mapping[str, models.Command] | None = None,
) -> dict:
    command = None
    if notification.voice_command_id:
        command = commands.get(notification.voice_command_id) if commands is not None else None
        if commands is None:
            command = (
                db.query(models.Command)
                .filter(models.Command.command_id == notification.voice_command_id)
                .one_or_none()
            )
    return {
        "id": notification.id,
        "device_id": notification.device_id,
        "content": notification.content,
        "voice_requested": notification.voice_requested,
        "voice_command_id": notification.voice_command_id,
        "voice_status": voice_status(command, notification.voice_requested),
        "created_at": iso_utc(notification.created_at) if notification.created_at else "",
    }


def list_notifications(db: Session, device_id: str, limit: int = 50) -> list[dict]:
    rows = (
        db.query(models.Notification)
        .filter(models.Notification.device_id == device_id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .limit(limit)
        .all()
    )
    command_ids = [row.voice_command_id for row in rows if row.voice_command_id]
    commands = (
        {
            command.command_id: command
            for command in db.query(models.Command).filter(models.Command.command_id.in_(command_ids)).all()
        }
        if command_ids
        else {}
    )
    return [serialize_notification(db, row, commands) for row in rows]


def create_notification(
    db: Session,
    device_id: str,
    payload: NotificationIn,
) -> tuple[models.Notification, models.Command | None]:
    ensure_device(db, device_id)
    notification = models.Notification(
        device_id=device_id,
        content=payload.content,
        voice_requested=payload.voice_broadcast,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    voice_command = None
    if payload.voice_broadcast:
        encoded = base64.b64encode(payload.content.encode("gb2312", errors="replace")).decode("ascii")
        voice_command = create_command(
            db,
            device_id,
            "voice.speak",
            parameter={"gb2312_base64": encoded},
            source="frontend",
            reason=payload.content,
            raw_payload={"notification_id": notification.id, "content": payload.content},
        )
        notification.voice_command_id = voice_command.command_id
        db.add(notification)
        db.commit()
        db.refresh(notification)

    return notification, voice_command
