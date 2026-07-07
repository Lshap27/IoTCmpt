from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.routes import set_mqtt_service
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.session import init_db
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.mqtt import MqttService
from app.services.websocket import manager


def _build_mqtt_handler(loop: asyncio.AbstractEventLoop):
    def handle(topic: str, payload: dict) -> None:
        db = SessionLocal()
        try:
            envelope = ingest_mqtt_message(db, topic, payload)
            if envelope is None:
                return
        finally:
            db.close()
        asyncio.run_coroutine_threadsafe(manager.broadcast(envelope.device_id, envelope.model_dump(mode="json")), loop)

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
