from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_llm_service
from app.core.config import get_settings
from app.db import models
from app.db.session import get_db
from app.schemas import CommandIn, WebSocketEnvelope
from app.services.commands import create_command, mark_published, serialize_command
from app.services.images import save_image
from app.services.llm import LLMService
from app.services.mqtt import MqttService
from app.services.telemetry import serialize_telemetry
from app.services.websocket import manager

router = APIRouter()
mqtt_service: MqttService | None = None


def set_mqtt_service(service: MqttService | None) -> None:
    global mqtt_service
    mqtt_service = service


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
    device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
    telemetry = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id)
        .order_by(models.Telemetry.sampled_at.desc())
        .first()
    )
    image = (
        db.query(models.ImageAsset)
        .filter(models.ImageAsset.device_id == device_id)
        .order_by(models.ImageAsset.created_at.desc())
        .first()
    )
    command = (
        db.query(models.Command)
        .filter(models.Command.device_id == device_id)
        .order_by(models.Command.created_at.desc())
        .first()
    )
    ai_result = (
        db.query(models.AiResult)
        .filter(models.AiResult.device_id == device_id)
        .order_by(models.AiResult.created_at.desc())
        .first()
    )
    return {
        "device": {
            "device_id": device_id,
            "display_name": device.display_name if device else device_id,
            "status": device.status if device else "unknown",
            "last_seen_at": device.last_seen_at.isoformat() if device and device.last_seen_at else None,
        },
        "telemetry": serialize_telemetry(telemetry) if telemetry else None,
        "image": {"id": image.id, "url": image.url, "created_at": image.created_at.isoformat()} if image else None,
        "command": serialize_command(command) if command else None,
        "ai_result": {
            "command_id": ai_result.command_id,
            "risk_level": ai_result.risk_level,
            "confidence": ai_result.confidence,
            "reason": ai_result.reason,
        }
        if ai_result
        else None,
    }


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
    latest = latest_device_state(device_id, db)
    message = llm.analyze(latest)
    command = create_command(
        db,
        device_id,
        message.type,
        parameter=message.parameter,
        source="llm",
        confidence=message.confidence,
        reason=message.reason,
        raw_payload=message.model_dump(mode="json"),
    )
    ai_result = models.AiResult(
        device_id=device_id,
        command_id=command.command_id,
        summary=message.reason,
        risk_level="unknown",
        model=get_settings().llm_model,
        confidence=message.confidence,
        reason=message.reason,
        raw_payload=message.model_dump(mode="json"),
    )
    db.add(ai_result)
    db.commit()
    if mqtt_service is not None:
        mqtt_service.publish_json(f"devices/{device_id}/command", serialize_command(command), qos=1)
        mark_published(db, command)
    envelope = WebSocketEnvelope(type="ai_result", device_id=device_id, payload=serialize_command(command))
    await manager.broadcast(device_id, envelope.model_dump(mode="json"))
    return serialize_command(command)
