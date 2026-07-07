from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.schemas import CommandAckIn, TelemetryIn, WebSocketEnvelope
from app.services.telemetry import record_command_ack, record_status, record_telemetry, serialize_telemetry


def parse_device_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "devices":
        return None
    return parts[1], parts[2]


def ingest_mqtt_message(db: Session, topic: str, payload: dict) -> WebSocketEnvelope | None:
    parsed = parse_device_topic(topic)
    if parsed is None:
        return None

    device_id, channel = parsed
    envelope_payload = payload
    event_type = channel

    try:
        if channel == "status":
            status = str(payload.get("status") or payload.get("value") or "unknown")
            device = record_status(db, device_id, status, payload)
            envelope_payload = {
                "device_id": device.device_id,
                "status": device.status,
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            }
        elif channel == "telemetry":
            sample = record_telemetry(db, TelemetryIn.model_validate({**payload, "device_id": device_id}))
            envelope_payload = serialize_telemetry(sample)
        elif channel == "command_ack":
            ack = CommandAckIn.model_validate({**payload, "device_id": device_id})
            command = record_command_ack(db, ack)
            envelope_payload = payload | {"known_command": command is not None}
        elif channel in {"event", "log"}:
            record_status(db, device_id, "online")
            db.add(
                models.DeviceEvent(
                    device_id=device_id,
                    type=str(payload.get("type") or channel),
                    severity=str(payload.get("severity") or "info"),
                    message=str(payload.get("message") or payload.get("raw") or ""),
                    raw_payload=payload,
                )
            )
            db.commit()
        else:
            return None
    except Exception as exc:
        event_type = "error"
        envelope_payload = {"topic": topic, "error": str(exc), "payload": payload}

    return WebSocketEnvelope(type=event_type, device_id=device_id, payload=envelope_payload)
