from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.routes import set_mqtt_service
from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.db.session import init_db
from app.schemas import CommandAckIn, TelemetryIn, WebSocketEnvelope
from app.services.mqtt import MqttService
from app.services.telemetry import record_command_ack, record_status, record_telemetry, serialize_telemetry
from app.services.websocket import manager


def _parse_device_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "devices":
        return None
    return parts[1], parts[2]


def _build_mqtt_handler(loop: asyncio.AbstractEventLoop):
    def handle(topic: str, payload: dict) -> None:
        parsed = _parse_device_topic(topic)
        if parsed is None:
            return
        device_id, channel = parsed
        envelope_payload = payload
        event_type = channel
        db = SessionLocal()
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
                return
        except Exception as exc:
            event_type = "error"
            envelope_payload = {"topic": topic, "error": str(exc), "payload": payload}
        finally:
            db.close()

        envelope = WebSocketEnvelope(type=event_type, device_id=device_id, payload=envelope_payload)
        asyncio.run_coroutine_threadsafe(manager.broadcast(device_id, envelope.model_dump(mode="json")), loop)

    return handle


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables:
        init_db()
    loop = asyncio.get_running_loop()
    mqtt_service = MqttService(settings, _build_mqtt_handler(loop))
    mqtt_service.start()
    app.state.mqtt_service = mqtt_service
    set_mqtt_service(mqtt_service)
    yield
    set_mqtt_service(None)
    mqtt_service.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AIoT Gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "aiot-gateway"}

    @app.websocket("/ws/devices/{device_id}")
    async def device_socket(websocket: WebSocket, device_id: str):
        await manager.connect(device_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(device_id, websocket)

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
