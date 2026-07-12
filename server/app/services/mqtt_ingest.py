from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.schemas import CommandAckIn, TelemetryIn, WebSocketEnvelope
from app.services.events import record_device_event, serialize_event
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
                "last_seen_at": iso_utc(device.last_seen_at) if device.last_seen_at else None,
            }
        elif channel == "telemetry":
            sample = record_telemetry(db, TelemetryIn.model_validate({**payload, "device_id": device_id}))
            envelope_payload = serialize_telemetry(sample)
        elif channel == "command_ack":
            ack = CommandAckIn.model_validate({**payload, "device_id": device_id})
            command = record_command_ack(db, ack)
            envelope_payload = payload | {"known_command": command is not None}
        elif channel == "event":
            record_status(db, device_id, "online")
            envelope_payload = serialize_event(record_device_event(db, device_id, payload))
        elif channel == "log":
            record_status(db, device_id, "online")
            record_device_event(db, device_id, {**payload, "type": str(payload.get("type") or "log")})
        else:
            return None
    except Exception as exc:
        event_type = "error"
        envelope_payload = {"topic": topic, "error": str(exc), "payload": payload}

    return WebSocketEnvelope(type=event_type, device_id=device_id, payload=envelope_payload)
