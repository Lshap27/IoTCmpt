from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db import models
from app.services.commands import ensure_device


def serialize_event(event: models.DeviceEvent) -> dict:
    return {
        "id": event.id,
        "device_id": event.device_id,
        "type": event.type,
        "severity": event.severity,
        "message": event.message,
        "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
        "created_at": event.created_at.isoformat(),
    }


def record_device_event(db: Session, device_id: str, payload: dict) -> models.DeviceEvent:
    ensure_device(db, device_id)
    event_type = str(payload.get("type") or "event")
    now = datetime.now(UTC).replace(tzinfo=None)

    # Devices publish transition events, but reconnects can replay the same edge.
    # Collapse only immediate duplicates; a later repeated alarm remains a new incident.
    latest = (
        db.query(models.DeviceEvent)
        .filter(models.DeviceEvent.device_id == device_id, models.DeviceEvent.type == event_type)
        .order_by(models.DeviceEvent.created_at.desc())
        .first()
    )
    if latest and latest.created_at >= now - timedelta(seconds=5):
        return latest

    event = models.DeviceEvent(
        device_id=device_id,
        type=event_type,
        severity=str(payload.get("severity") or "info"),
        message=str(payload.get("message") or payload.get("raw") or ""),
        raw_payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def acknowledge_event(db: Session, device_id: str, event_id: int) -> models.DeviceEvent | None:
    event = (
        db.query(models.DeviceEvent)
        .filter(models.DeviceEvent.id == event_id, models.DeviceEvent.device_id == device_id)
        .one_or_none()
    )
    if event is None:
        return None
    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(UTC).replace(tzinfo=None)
        db.add(event)
        db.commit()
        db.refresh(event)
    return event
