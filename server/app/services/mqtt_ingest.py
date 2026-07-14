from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import CommandAckIn, TelemetryIn, WebSocketEnvelope
from app.services.commands import ensure_device
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
    trace_id = payload.get("trace_id")
    body = payload.get("payload") if payload.get("schema_version") == "2.0" else payload
    if not isinstance(body, dict):
        body = payload
    envelope_payload = body
    event_type = channel

    try:
        if channel == "status":
            event_type = "device.status_changed"
            status = str(body.get("status") or body.get("value") or "unknown")
            device = record_status(db, device_id, status, payload)
            envelope_payload = {
                "device_id": device.device_id,
                "status": device.status,
                "last_seen_at": iso_utc(device.last_seen_at) if device.last_seen_at else None,
            }
        elif channel == "telemetry":
            event_type = "telemetry.received"
            sample = record_telemetry(db, TelemetryIn.model_validate({**body, "device_id": device_id}))
            envelope_payload = serialize_telemetry(sample)
        elif channel == "command_ack":
            ack = CommandAckIn.model_validate({**body, "trace_id": trace_id, "device_id": device_id})
            command = record_command_ack(db, ack)
            envelope_payload = body | {"known_command": command is not None}
            event_type = "command.status_changed"
        elif channel == "capabilities":
            ensure_device(db, device_id)
            capability = (
                db.query(models.DeviceCapability).filter(models.DeviceCapability.device_id == device_id).one_or_none()
            )
            if capability is None:
                capability = models.DeviceCapability(device_id=device_id)
            capability.protocol_version = str(body.get("protocol_version") or "2.0")
            capability.firmware_version = str(body.get("firmware_version") or "unknown")
            capability.hardware_model = str(body.get("hardware_model") or "ESP32-S3")
            capability.commands = list(body.get("commands") or [])
            capability.capability_hash = str(body.get("capability_hash") or "")
            db.add(capability)
            db.commit()
            envelope_payload = body
            event_type = "device.capabilities_changed"
        elif channel == "event":
            record_status(db, device_id, "online")
            envelope_payload = {"kind": "event", **serialize_event(record_device_event(db, device_id, body))}
            event_type = "perception.updated"
        elif channel == "log":
            record_status(db, device_id, "online")
            record_device_event(db, device_id, {**body, "type": str(body.get("type") or "log")})
            envelope_payload = {"kind": "log", **body}
            event_type = "perception.updated"
        else:
            return None
    except Exception as exc:
        event_type = "system.error"
        envelope_payload = {"code": "mqtt_ingest_failed", "message": str(exc), "topic": topic, "payload": payload}

    if trace_id:
        db.add(
            models.TraceEvent(
                event_id=f"trace-{uuid4().hex[:20]}",
                trace_id=str(trace_id),
                device_id=device_id,
                component="mqtt",
                event_type=f"mqtt.{channel}.received",
                status=str(envelope_payload.get("status") or "received"),
                detail={"topic": topic, "event_type": event_type},
            )
        )
        db.commit()

    return WebSocketEnvelope(type=event_type, device_id=device_id, trace_id=trace_id, payload=envelope_payload)
