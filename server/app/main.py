from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.schemas import HealthOut, WebSocketEnvelope
from app.services.autopilot import AutoPilot
from app.services.llm import LLMService
from app.services.mqtt import MqttGateway
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.websocket import manager


def _ingest_sync(topic: str, payload: dict[str, Any]) -> WebSocketEnvelope | None:
    db = SessionLocal()
    try:
        return ingest_mqtt_message(db, topic, payload)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables:
        init_db()

    autopilot = AutoPilot(settings, LLMService(settings))
    mqtt_service = MqttGateway(settings)
    autopilot.mqtt_service = mqtt_service

    async def handle_mqtt_message(topic: str, payload: dict[str, Any]) -> None:
        # DB writes stay on a worker thread; broadcast and autopilot run on the event loop.
        envelope = await asyncio.to_thread(_ingest_sync, topic, payload)
        if envelope is None:
            return
        await manager.broadcast(envelope.device_id, envelope.model_dump(mode="json"))
        if envelope.type == "telemetry":
            autopilot.maybe_trigger(envelope.device_id, envelope.payload)

    mqtt_service.start(handle_mqtt_message)
    app.state.mqtt_service = mqtt_service
    app.state.autopilot = autopilot
    yield
    await mqtt_service.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AIoT Gateway",
        version="0.1.0",
        lifespan=lifespan,
        # Clean operation ids (route function names) -> clean generated SDK names.
        generate_unique_id_function=lambda route: route.name,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

    @app.get("/health", response_model=HealthOut)
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
