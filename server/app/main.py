from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.schemas import HealthOut, WebSocketEnvelope
from app.services.autopilot import AutoPilot
from app.services.llm import LLMService
from app.services.mqtt import MqttGateway
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.pose import PoseService
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
    pose_service = PoseService(settings)
    autopilot.mqtt_service = mqtt_service
    pose_service.result_handler = autopilot.on_pose_result

    async def handle_mqtt_message(topic: str, payload: dict[str, Any]) -> None:
        # DB writes stay on a worker thread; broadcast and autopilot run on the event loop.
        envelope = await asyncio.to_thread(_ingest_sync, topic, payload)
        if envelope is None:
            return
        await manager.broadcast(envelope.device_id, envelope.model_dump(mode="json"))
        if envelope.type == "telemetry":
            autopilot.maybe_trigger(envelope.device_id, envelope.payload)
        elif envelope.type == "event" and envelope.payload.get("type") == "smoke.detected":
            autopilot.trigger_smoke(envelope.device_id)

    mqtt_service.start(handle_mqtt_message)
    await pose_service.start()
    app.state.mqtt_service = mqtt_service
    app.state.autopilot = autopilot
    app.state.pose_service = pose_service
    yield
    await pose_service.stop()
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

    @app.middleware("http")
    async def limit_upload_size(request: Request, call_next):
        # 必须在 multipart 解析之前按 Content-Length 拒绝超大请求；
        # 到路由层再检查时整个请求体已经被吞进临时文件，限制形同虚设。
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            if (
                content_length
                and content_length.isdigit()
                and int(content_length) > settings.max_upload_bytes + 64 * 1024
            ):
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
        return await call_next(request)

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
            pass
        finally:
            # 任何异常（如客户端发来二进制帧）都要注销连接，避免死连接残留
            manager.disconnect(device_id, websocket)

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
