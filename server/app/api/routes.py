from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_run_application,
    get_automation_application,
    get_automation_plan_application,
    get_command_application,
    get_device_queries,
    get_pose_service,
)
from app.application.automation import AiRunApplicationService, AutomationApplicationService
from app.application.automation_plans import AutomationPlanApplicationService
from app.application.commands import CommandApplicationService
from app.application.queries import DeviceQueryApplicationService
from app.core.config import get_settings
from app.core.timeutil import iso_utc
from app.db import models
from app.db.session import get_db
from app.domain.commands import CommandRejected, CommandRequest
from app.schemas import (
    DeviceSummary,
    EventOut,
    ImageAssetOut,
    LatestState,
    NotificationIn,
    NotificationOut,
    PoseAnalyzeAccepted,
    TelemetryBucketPoint,
    TelemetryPoint,
    WebSocketEnvelope,
)
from app.schemas_v1 import (
    AiRunCreate,
    AiRunOut,
    AiStrategyOut,
    AutomationPlanActivateIn,
    AutomationPlanEventOut,
    AutomationPlanOut,
    AutomationPolicyIn,
    AutomationPolicyOut,
    CommandCreateV1,
    CommandV1Out,
    DeviceCapabilitiesOut,
    TraceTimelineOut,
)
from app.services.events import acknowledge_event, serialize_event
from app.services.images import save_image
from app.services.pose import PoseService
from app.services.telemetry import fetch_history_bucketed
from app.services.voice_commands import submit_speech
from app.services.websocket import manager

router = APIRouter()


@router.get("/devices", response_model=list[DeviceSummary])
async def list_devices(queries: DeviceQueryApplicationService = Depends(get_device_queries)):
    return await queries.list_devices()


@router.get("/devices/{device_id}/latest", response_model=LatestState)
async def latest_device_state(
    device_id: str,
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    return await queries.snapshot(device_id)


@router.get("/devices/{device_id}/history", response_model=list[TelemetryPoint])
async def telemetry_history(
    device_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    return await queries.history(device_id, limit=limit)


@router.get("/devices/{device_id}/history/bucketed", response_model=list[TelemetryBucketPoint])
def telemetry_history_bucketed(
    device_id: str,
    bucket: int = Query(default=60, ge=10, le=86400, description="降采样窗口秒数"),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(status_code=400, detail="Bucketed history requires PostgreSQL/TimescaleDB")
    return fetch_history_bucketed(db, device_id, bucket, limit)


@router.post("/devices/{device_id}/images", response_model=ImageAssetOut)
async def upload_image(
    device_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    pose: PoseService = Depends(get_pose_service),
):
    asset = save_image(db, get_settings(), device_id, file)
    envelope = WebSocketEnvelope(
        type="perception.updated",
        device_id=device_id,
        payload={
            "kind": "image",
            "id": asset.id,
            "url": asset.url,
            "created_at": iso_utc(asset.created_at),
        },
    )
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    await pose.enqueue(device_id, asset.id)
    return {"id": asset.id, "device_id": asset.device_id, "url": asset.url, "created_at": iso_utc(asset.created_at)}


@router.post("/devices/{device_id}/pose/analyze", response_model=PoseAnalyzeAccepted, status_code=202)
async def analyze_latest_pose(
    device_id: str,
    db: Session = Depends(get_db),
    pose: PoseService = Depends(get_pose_service),
):
    source = (
        db.query(models.ImageAsset)
        .filter(models.ImageAsset.device_id == device_id, models.ImageAsset.kind == "capture")
        .order_by(models.ImageAsset.created_at.desc())
        .first()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="No image is available for pose analysis")
    if not pose.settings.pose_enabled:
        raise HTTPException(status_code=503, detail="Pose analysis is disabled")
    await pose.enqueue(device_id, source.id)
    return {"queued": True, "source_image_id": source.id}


@router.get("/devices/{device_id}/events", response_model=list[EventOut])
async def device_events(
    device_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    return await queries.events(device_id, limit=min(limit, 500))


@router.post("/devices/{device_id}/events/{event_id}/ack", response_model=EventOut)
def ack_device_event(device_id: str, event_id: int, db: Session = Depends(get_db)):
    event = acknowledge_event(db, device_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return serialize_event(event)


@router.post("/devices/{device_id}/commands", response_model=CommandV1Out, status_code=status.HTTP_202_ACCEPTED)
async def send_command(
    device_id: str,
    payload: CommandCreateV1,
    request: Request,
    commands: CommandApplicationService = Depends(get_command_application),
):
    try:
        return await commands.submit(
            CommandRequest(
                device_id=device_id,
                type=payload.type,
                parameter=payload.parameter,
                source="frontend",
                reason=payload.reason,
                trace_id=request.state.trace_id,
                idempotency_key=payload.idempotency_key,
                expires_at=payload.expires_at.replace(tzinfo=None) if payload.expires_at else None,
            )
        )
    except CommandRejected as exc:
        raise HTTPException(status_code=422, detail={"code": exc.error_code, "message": str(exc)}) from exc


@router.get("/devices/{device_id}/commands/{command_id}", response_model=CommandV1Out)
async def get_command_v1(
    device_id: str,
    command_id: str,
    commands: CommandApplicationService = Depends(get_command_application),
):
    command = await commands.get(device_id, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return command


@router.get("/devices/{device_id}/capabilities", response_model=DeviceCapabilitiesOut)
async def get_device_capabilities(
    device_id: str,
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    capability = await queries.capabilities(device_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Device capabilities have not been advertised")
    return capability


@router.get("/devices/{device_id}/automation-policy", response_model=AutomationPolicyOut)
async def get_automation_policy(
    device_id: str,
    automation: AutomationApplicationService = Depends(get_automation_application),
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    await plans.ensure_system_plan(device_id)
    return await automation.get_policy(device_id)


@router.put("/devices/{device_id}/automation-policy", response_model=AutomationPolicyOut)
async def update_automation_policy(
    device_id: str,
    payload: AutomationPolicyIn,
    request: Request,
    automation: AutomationApplicationService = Depends(get_automation_application),
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    try:
        await plans.ensure_system_plan(device_id)
        updated = await automation.update_policy(device_id, payload.model_dump(exclude_none=True))
        await manager.broadcast(
            device_id,
            WebSocketEnvelope(
                type="automation.policy.changed",
                device_id=device_id,
                trace_id=request.state.trace_id,
                payload=updated,
            ).model_dump(mode="json"),
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devices/{device_id}/ai/runs", response_model=AiRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_ai_run(
    device_id: str,
    payload: AiRunCreate,
    request: Request,
    runs: AiRunApplicationService = Depends(get_ai_run_application),
):
    return await runs.create(device_id, payload.model_dump(mode="json"), request.state.trace_id)


@router.get("/devices/{device_id}/automation-plans", response_model=list[AutomationPlanOut])
async def list_automation_plans(
    device_id: str,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await plans.list_plans(device_id)


@router.get("/devices/{device_id}/automation-plans/{plan_id}", response_model=AutomationPlanOut)
async def get_automation_plan(
    device_id: str,
    plan_id: str,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    plan = await plans.get(device_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Automation plan not found")
    return plan


@router.get(
    "/devices/{device_id}/automation-plans/{plan_id}/events",
    response_model=list[AutomationPlanEventOut],
)
async def list_automation_plan_events(
    device_id: str,
    plan_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    if await plans.get(device_id, plan_id) is None:
        raise HTTPException(status_code=404, detail="Automation plan not found")
    return await plans.events(device_id, plan_id, limit)


async def _transition_plan(
    device_id: str,
    plan_id: str,
    action: str,
    plans: AutomationPlanApplicationService,
    request: Request,
    *,
    replace_active: bool = False,
) -> dict:
    try:
        result = await plans.transition(device_id, plan_id, action, replace_active=replace_active)
        await request.app.state.automation_runtime.evaluate(device_id)
        return await plans.get(device_id, plan_id) or result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devices/{device_id}/automation-plans/{plan_id}/activate", response_model=AutomationPlanOut)
async def activate_automation_plan(
    device_id: str,
    plan_id: str,
    payload: AutomationPlanActivateIn,
    request: Request,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await _transition_plan(device_id, plan_id, "activate", plans, request, replace_active=payload.replace_active)


@router.post("/devices/{device_id}/automation-plans/{plan_id}/pause", response_model=AutomationPlanOut)
async def pause_automation_plan(
    device_id: str,
    plan_id: str,
    request: Request,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await _transition_plan(device_id, plan_id, "pause", plans, request)


@router.post("/devices/{device_id}/automation-plans/{plan_id}/resume", response_model=AutomationPlanOut)
async def resume_automation_plan(
    device_id: str,
    plan_id: str,
    request: Request,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await _transition_plan(device_id, plan_id, "resume", plans, request)


@router.post("/devices/{device_id}/automation-plans/{plan_id}/cancel", response_model=AutomationPlanOut)
async def cancel_automation_plan(
    device_id: str,
    plan_id: str,
    request: Request,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await _transition_plan(device_id, plan_id, "cancel", plans, request)


@router.get("/devices/{device_id}/ai/strategies", response_model=list[AiStrategyOut])
async def list_ai_strategies(
    device_id: str,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await plans.list_strategies(device_id)


@router.get("/devices/{device_id}/ai/strategies/{strategy_id}", response_model=AiStrategyOut)
async def get_ai_strategy(
    device_id: str,
    strategy_id: str,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    strategy = await plans.get_strategy(device_id, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="AI strategy not found")
    return strategy


async def _resolve_strategy(
    device_id: str,
    strategy_id: str,
    action: str,
    plans: AutomationPlanApplicationService,
) -> dict:
    try:
        return await plans.resolve_strategy(device_id, strategy_id, action)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devices/{device_id}/ai/strategies/{strategy_id}/approve", response_model=AiStrategyOut)
async def approve_ai_strategy(
    device_id: str,
    strategy_id: str,
    request: Request,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    result = await _resolve_strategy(device_id, strategy_id, "approve", plans)
    await request.app.state.automation_runtime.evaluate(device_id)
    return result


@router.post("/devices/{device_id}/ai/strategies/{strategy_id}/reject", response_model=AiStrategyOut)
async def reject_ai_strategy(
    device_id: str,
    strategy_id: str,
    plans: AutomationPlanApplicationService = Depends(get_automation_plan_application),
):
    return await _resolve_strategy(device_id, strategy_id, "reject", plans)


@router.get("/devices/{device_id}/ai/runs/{run_id}", response_model=AiRunOut)
async def get_ai_run(
    device_id: str,
    run_id: str,
    runs: AiRunApplicationService = Depends(get_ai_run_application),
):
    run = await runs.get(device_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return run


@router.get("/devices/{device_id}/ai/runs", response_model=list[AiRunOut])
async def list_ai_runs(
    device_id: str,
    kind: str | None = Query(default=None),
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    runs: AiRunApplicationService = Depends(get_ai_run_application),
):
    return await runs.list(device_id, kind=kind, status=run_status, limit=limit)


@router.post("/devices/{device_id}/ai/runs/{run_id}/cancel", response_model=AiRunOut)
async def cancel_ai_run(
    device_id: str,
    run_id: str,
    runs: AiRunApplicationService = Depends(get_ai_run_application),
):
    run = await runs.cancel(device_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return run


@router.get("/diagnostics/traces/{trace_id}", response_model=TraceTimelineOut)
async def get_trace_timeline(
    trace_id: str,
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    return await queries.trace_timeline(trace_id)


@router.get("/diagnostics/overview")
async def get_diagnostics_overview(
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    overview = await queries.diagnostics_overview()
    settings = get_settings()
    return {
        **overview,
        "mcp": {
            "external_enabled": settings.mcp_enabled,
            "internal_configured": bool(settings.mcp_internal_token),
        },
    }


@router.get("/devices/{device_id}/notifications", response_model=list[NotificationOut])
async def device_notifications(
    device_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
):
    return await queries.notifications(device_id, limit=limit)


@router.post("/devices/{device_id}/notifications", response_model=NotificationOut, status_code=201)
async def send_notification(
    device_id: str,
    payload: NotificationIn,
    request: Request,
    queries: DeviceQueryApplicationService = Depends(get_device_queries),
    commands: CommandApplicationService = Depends(get_command_application),
):
    response = await queries.create_notification(device_id, payload.content)
    if payload.voice_broadcast:
        command = await submit_speech(
            commands,
            device_id=device_id,
            text=payload.content,
            source="frontend",
            reason=payload.content,
            trace_id=request.state.trace_id,
            idempotency_key=f"notification:{response['id']}",
        )
        response = await queries.link_notification_command(response["id"], command["command_id"])
    envelope = WebSocketEnvelope(type="notification.created", device_id=device_id, payload=response)
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return response
