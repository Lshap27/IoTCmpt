from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas import CommandAckResponse, CommandCreate
from app.services.command_service import ack_command, create_command, get_oldest_pending_command

router = APIRouter(prefix="/api/command", tags=["commands"])


@router.post("")
def send_command(payload: CommandCreate, db: Session = Depends(get_db)):
    command = create_command(db, payload)
    return {
        "status": "success",
        "message": f"指令已下发: {command.command}",
        "id": command.id,
        "command": command.command,
        "parameter": command.parameter,
    }


@router.get("/pending")
def get_pending_command(db: Session = Depends(get_db)):
    command = get_oldest_pending_command(db)
    if command is None:
        return {"status": "empty", "message": "暂无待执行指令"}
    device, legacy_command = command.legacy_device_command
    return {
        "status": "success",
        "id": command.id,
        "device": device,
        "command": command.command,
        "legacy_command": legacy_command,
        "value": command.parameter,
        "parameter": command.parameter,
        "confidence": command.confidence,
        "created_at": command.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.post("/ack/{cmd_id}", response_model=CommandAckResponse)
def acknowledge_command(cmd_id: int, db: Session = Depends(get_db)):
    command = ack_command(db, cmd_id)
    if command is None:
        raise HTTPException(status_code=404, detail="指令不存在或已执行")
    return {"status": "success", "message": f"指令 {cmd_id} 已确认执行"}
