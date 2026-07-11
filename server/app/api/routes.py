from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import (
    get_autopilot,
    get_autopilot_or_none,
    get_llm_service,
    get_mqtt_gateway,
    get_pose_service,
)
from app.core.config import get_settings
from app.db import models
from app.db.session import get_db
from app.schemas import (
    AiDecisionOut,
    AutopilotIn,
    AutopilotState,
    CommandIn,
    CommandOut,
    DeviceSummary,
    EventOut,
    ImageAssetOut,
    LatestState,
    PoseAnalyzeAccepted,
    TelemetryBucketPoint,
    TelemetryPoint,
    WebSocketEnvelope,
)
from app.services.analysis import collect_device_snapshot, run_ai_analysis
from app.services.autopilot import AutoPilot
from app.services.commands import create_command, mark_published, serialize_command
from app.services.events import acknowledge_event, serialize_event
from app.services.images import save_image
from app.services.llm import LLMService
from app.services.mqtt import MqttGateway
from app.services.pose import PoseService
from app.services.telemetry import fetch_history_bucketed, serialize_telemetry
from app.services.websocket import manager

router = APIRouter()


@router.get("/devices", response_model=list[DeviceSummary])
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(models.Device).order_by(models.Device.device_id.asc()).all()
    return [
        {
            "device_id": device.device_id,
            "display_name": device.display_name,
            "status": device.status,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        }
        for device in devices
    ]


@router.get("/devices/{device_id}/latest", response_model=LatestState)
def latest_device_state(
    device_id: str,
    db: Session = Depends(get_db),
    autopilot: AutoPilot | None = Depends(get_autopilot_or_none),
):
    snapshot = collect_device_snapshot(db, device_id)
    snapshot["autopilot"] = {"enabled": autopilot.is_enabled(device_id)} if autopilot else None
    return snapshot


@router.get("/devices/{device_id}/history", response_model=list[TelemetryPoint])
def telemetry_history(device_id: str, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id)
        .order_by(models.Telemetry.sampled_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_telemetry(row) for row in rows]


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
        type="image",
        device_id=device_id,
        payload={"id": asset.id, "url": asset.url, "created_at": asset.created_at.isoformat()},
    )
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    await pose.enqueue(device_id, asset.id)
    return {"id": asset.id, "device_id": asset.device_id, "url": asset.url, "created_at": asset.created_at}


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
def device_events(
    device_id: str,
    event_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(models.DeviceEvent).filter(models.DeviceEvent.device_id == device_id)
    if event_type:
        query = query.filter(models.DeviceEvent.type == event_type)
    rows = query.order_by(models.DeviceEvent.created_at.desc()).limit(limit).all()
    return [serialize_event(row) for row in rows]


@router.post("/devices/{device_id}/events/{event_id}/ack", response_model=EventOut)
def ack_device_event(device_id: str, event_id: int, db: Session = Depends(get_db)):
    event = acknowledge_event(db, device_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return serialize_event(event)


@router.post("/devices/{device_id}/commands", response_model=CommandOut)
async def send_command(
    device_id: str,
    payload: CommandIn,
    db: Session = Depends(get_db),
    mqtt: MqttGateway | None = Depends(get_mqtt_gateway),
):
    command = create_command(db, device_id, payload.type, parameter=payload.parameter, reason=payload.reason)
    if mqtt is not None:
        await mqtt.publish_json(f"devices/{device_id}/command", serialize_command(command), qos=1)
        mark_published(db, command)
    envelope = WebSocketEnvelope(type="command", device_id=device_id, payload=serialize_command(command))
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return serialize_command(command)


@router.post("/devices/{device_id}/ai/analyze", response_model=AiDecisionOut)
async def analyze_device(
    device_id: str,
    db: Session = Depends(get_db),
    llm: LLMService = Depends(get_llm_service),
    mqtt: MqttGateway | None = Depends(get_mqtt_gateway),
):
    return await run_ai_analysis(db, device_id, llm, mqtt, trigger="manual")


@router.get("/devices/{device_id}/autopilot", response_model=AutopilotState)
def get_autopilot_state(device_id: str, autopilot: AutoPilot = Depends(get_autopilot)):
    return autopilot.describe(device_id)


@router.put("/devices/{device_id}/autopilot", response_model=AutopilotState)
async def update_autopilot_state(
    device_id: str,
    payload: AutopilotIn,
    autopilot: AutoPilot = Depends(get_autopilot),
):
    autopilot.set_enabled(device_id, payload.enabled)
    state = autopilot.describe(device_id)
    envelope = WebSocketEnvelope(type="autopilot", device_id=device_id, payload=state)
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return state
