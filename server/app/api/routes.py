from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_llm_service
from app.core.config import get_settings
from app.db import models
from app.db.session import get_db
from app.schemas import AutopilotIn, CommandIn, WebSocketEnvelope
from app.services.analysis import collect_device_snapshot, run_ai_analysis
from app.services.autopilot import AutoPilot
from app.services.commands import create_command, mark_published, serialize_command
from app.services.images import save_image
from app.services.llm import LLMService
from app.services.mqtt import MqttService
from app.services.telemetry import serialize_telemetry
from app.services.websocket import manager

router = APIRouter()
mqtt_service: MqttService | None = None
autopilot_service: AutoPilot | None = None


def set_mqtt_service(service: MqttService | None) -> None:
    global mqtt_service
    mqtt_service = service


def set_autopilot(service: AutoPilot | None) -> None:
    global autopilot_service
    autopilot_service = service


@router.get("/devices")
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


@router.get("/devices/{device_id}/latest")
def latest_device_state(device_id: str, db: Session = Depends(get_db)):
    snapshot = collect_device_snapshot(db, device_id)
    snapshot["autopilot"] = {"enabled": autopilot_service.is_enabled(device_id)} if autopilot_service else None
    return snapshot


@router.get("/devices/{device_id}/history")
def telemetry_history(device_id: str, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id)
        .order_by(models.Telemetry.sampled_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_telemetry(row) for row in rows]


@router.post("/devices/{device_id}/images")
async def upload_image(device_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    asset = save_image(db, get_settings(), device_id, file)
    envelope = WebSocketEnvelope(
        type="image",
        device_id=device_id,
        payload={"id": asset.id, "url": asset.url, "created_at": asset.created_at.isoformat()},
    )
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return {"id": asset.id, "device_id": asset.device_id, "url": asset.url, "created_at": asset.created_at}


@router.post("/devices/{device_id}/commands")
async def send_command(device_id: str, payload: CommandIn, db: Session = Depends(get_db)):
    command = create_command(db, device_id, payload.type, parameter=payload.parameter, reason=payload.reason)
    if mqtt_service is not None:
        mqtt_service.publish_json(f"devices/{device_id}/command", serialize_command(command), qos=1)
        mark_published(db, command)
    envelope = WebSocketEnvelope(type="command", device_id=device_id, payload=serialize_command(command))
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return serialize_command(command)


@router.post("/devices/{device_id}/ai/analyze")
async def analyze_device(
    device_id: str,
    db: Session = Depends(get_db),
    llm: LLMService = Depends(get_llm_service),
):
    return await run_ai_analysis(db, device_id, llm, mqtt_service, trigger="manual")


@router.get("/devices/{device_id}/autopilot")
def get_autopilot_state(device_id: str):
    if autopilot_service is None:
        raise HTTPException(status_code=503, detail="Autopilot is not available")
    return autopilot_service.describe(device_id)


@router.put("/devices/{device_id}/autopilot")
async def update_autopilot_state(device_id: str, payload: AutopilotIn):
    if autopilot_service is None:
        raise HTTPException(status_code=503, detail="Autopilot is not available")
    autopilot_service.set_enabled(device_id, payload.enabled)
    state = autopilot_service.describe(device_id)
    envelope = WebSocketEnvelope(type="autopilot", device_id=device_id, payload=state)
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return state
