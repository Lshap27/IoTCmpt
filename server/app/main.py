from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.adapters.automation_plans import SqlAlchemyAutomationPlanRepository
from app.adapters.mcp_server import create_mcp_server
from app.adapters.outbox import OutboxDispatcher
from app.adapters.persistence import (
    SqlAlchemyAiRunRepository,
    SqlAlchemyAutomationRepository,
    SqlAlchemyCommandRepository,
    SqlAlchemyDeviceQueryRepository,
)
from app.adapters.realtime import RealtimeEventWriter, RealtimeRelay
from app.adapters.triggers import enqueue_event_run
from app.api.routes import router as api_router
from app.application.automation import AiRunApplicationService, AutomationApplicationService
from app.application.automation_plans import AutomationPlanApplicationService
from app.application.commands import CommandApplicationService
from app.application.queries import DeviceQueryApplicationService
from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal, init_db
from app.schemas import HealthOut, WebSocketEnvelope
from app.services.automation_runtime import AutomationRuntimeService
from app.services.mqtt import MqttGateway
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.pose import PoseService
from app.services.sedentary import detect_sedentary_event
from app.services.websocket import manager

LOGGER = logging.getLogger(__name__)


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

    mqtt_service = MqttGateway(settings)
    pose_service = PoseService(settings)
    command_repository = SqlAlchemyCommandRepository(SessionLocal)
    command_notifier = RealtimeEventWriter(SessionLocal)
    app.state.command_application = CommandApplicationService(command_repository, command_notifier)
    plan_repository = SqlAlchemyAutomationPlanRepository(SessionLocal)
    plan_application = AutomationPlanApplicationService(plan_repository)
    automation_runtime = AutomationRuntimeService(
        settings,
        SessionLocal,
        app.state.command_application,
        plan_repository,
    )

    async def evaluate_automation(device_id: str) -> None:
        try:
            await automation_runtime.evaluate(device_id)
        except Exception:
            LOGGER.exception("automation evaluation failed for %s", device_id)

    async def handle_mqtt_message(topic: str, payload: dict[str, Any]) -> None:
        # DB writes stay on a worker thread; deterministic automation runs after committed ingress.
        envelope = await asyncio.to_thread(_ingest_sync, topic, payload)
        if envelope is None:
            return
        await manager.broadcast(envelope.device_id, envelope.model_dump(mode="json"))
        if envelope.type in {"telemetry.received", "device.status_changed", "device.capabilities_changed"}:
            await evaluate_automation(envelope.device_id)
        elif envelope.type == "command.status_changed":
            command_id = str(envelope.payload.get("command_id") or "")
            command_status = str(envelope.payload.get("status") or "")
            if command_id:
                try:
                    await automation_runtime.reconcile_command(envelope.device_id, command_id, command_status)
                except Exception:
                    LOGGER.exception("automation command reconciliation failed for %s", command_id)
        if topic.endswith("/event"):
            event_payload = payload.get("payload") if payload.get("schema_version") == "2.0" else payload
            event_type = str((event_payload or {}).get("type") or "event")
            await asyncio.to_thread(enqueue_event_run, SessionLocal, settings, envelope.device_id, event_type)

    async def handle_pose_result(device_id: str, payload: dict[str, Any]) -> None:
        await evaluate_automation(device_id)
        event = await asyncio.to_thread(detect_sedentary_event, SessionLocal, device_id, int(payload["id"]))
        if event is None:
            return
        await manager.broadcast(
            device_id,
            WebSocketEnvelope(
                type="perception.updated",
                device_id=device_id,
                payload={"kind": "event", **event},
            ).model_dump(mode="json"),
        )
        await asyncio.to_thread(enqueue_event_run, SessionLocal, settings, device_id, event["type"])

    pose_service.result_handler = handle_pose_result
    mqtt_service.start(handle_mqtt_message)
    app.state.automation_application = AutomationApplicationService(SqlAlchemyAutomationRepository(SessionLocal))
    app.state.automation_plan_application = plan_application
    app.state.ai_run_application = AiRunApplicationService(SqlAlchemyAiRunRepository(SessionLocal))
    app.state.device_queries = DeviceQueryApplicationService(SqlAlchemyDeviceQueryRepository(SessionLocal))
    outbox = OutboxDispatcher(
        SessionLocal,
        mqtt_service,
        command_notifier,
        settings.command_ack_timeout_seconds,
        settings.outbox_lease_seconds,
    )
    realtime_relay = RealtimeRelay(SessionLocal)
    outbox.start()
    realtime_relay.start()
    await pose_service.start()
    await automation_runtime.start()
    app.state.mqtt_service = mqtt_service
    app.state.pose_service = pose_service
    app.state.automation_runtime = automation_runtime
    app.state.mqtt_message_handler = handle_mqtt_message
    app.state.outbox_dispatcher = outbox
    app.state.realtime_relay = realtime_relay
    mcp_starlette = app.state.mcp_starlette
    async with mcp_starlette.router.lifespan_context(mcp_starlette):
        try:
            yield
        finally:
            await realtime_relay.stop()
    await automation_runtime.stop()
    await outbox.stop()
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
    if settings.mcp_enabled and (not settings.mcp_read_token or not settings.mcp_control_token):
        raise ValueError("MCP read and control tokens are required when MCP is enabled")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or f"trace-{uuid4().hex[:16]}"
        request.state.trace_id = trace_id
        # 必须在 multipart 解析之前按 Content-Length 拒绝超大请求；
        # 到路由层再检查时整个请求体已经被吞进临时文件，限制形同虚设。
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            if (
                content_length
                and content_length.isdigit()
                and int(content_length) > settings.max_upload_bytes + 64 * 1024
            ):
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large", "trace_id": trace_id},
                    headers={"x-trace-id": trace_id},
                )
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        LOGGER.info(
            "request component=http operation=%s path=%s status=%s trace_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            trace_id,
        )
        return response

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

    @app.get("/health", response_model=HealthOut)
    def health():
        return {"status": "ok", "service": "aiot-gateway"}

    @app.get("/health/live", response_model=HealthOut)
    def health_live():
        return {"status": "ok", "service": "aiot-gateway"}

    @app.get("/health/ready")
    def health_ready(request: Request):
        mqtt = getattr(request.app.state, "mqtt_service", None)
        now = datetime.now(UTC).replace(tzinfo=None)
        database = "connected"
        worker = "unavailable"
        migration = "unknown"
        try:
            with SessionLocal() as db:
                db.execute(models.Device.__table__.select().limit(1))
                recent = (
                    db.query(models.RuntimeInstance)
                    .filter(
                        models.RuntimeInstance.role == "ai-worker",
                        models.RuntimeInstance.heartbeat_at >= now - timedelta(seconds=45),
                    )
                    .first()
                )
                worker = "healthy" if recent else "unavailable"
                version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
                migration = "current" if version == "0010" else str(version or "missing")
        except Exception:
            database = "unavailable"
        return {
            "status": "ready" if database == "connected" else "not_ready",
            "service": "aiot-gateway",
            "dependencies": {
                "database": database,
                "mqtt": "connected" if mqtt and mqtt.connected else "disconnected",
                "worker": worker,
                "mcp": "enabled",
                "migration": migration,
            },
        }

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

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def mcp_redirect():
        return RedirectResponse(url="/mcp/", status_code=307)

    app.include_router(api_router, prefix="/api/v1")
    if not settings.mcp_internal_token:
        raise ValueError("AIOT_MCP_INTERNAL_TOKEN is required")
    internal_mcp_token = settings.mcp_internal_token
    mcp_server, mcp_starlette, mcp_asgi = create_mcp_server(app, settings, internal_mcp_token)
    app.state.internal_mcp_token = internal_mcp_token
    app.state.mcp_server = mcp_server
    app.state.mcp_starlette = mcp_starlette
    app.mount("/mcp", mcp_asgi, name="mcp")
    return app


app = create_app()
