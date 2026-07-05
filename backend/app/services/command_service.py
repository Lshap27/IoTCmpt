from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DeviceCommand
from app.schemas import CloudCommandResponse, CommandCreate

ALLOWED_COMMANDS = {"none", "window.open", "window.close", "alarm.on", "alarm.off"}

LEGACY_COMMAND_MAP = {
    ("window", "open"): "window.open",
    ("window", "close"): "window.close",
    ("window", "on"): "window.open",
    ("window", "off"): "window.close",
    ("alarm", "on"): "alarm.on",
    ("alarm", "off"): "alarm.off",
    ("beeper", "on"): "alarm.on",
    ("beeper", "off"): "alarm.off",
    ("buzzer", "on"): "alarm.on",
    ("buzzer", "off"): "alarm.off",
    ("light", "on"): "alarm.on",
    ("light", "off"): "alarm.off",
}


def normalize_command(device: Optional[str], command: Optional[str]) -> str:
    raw_command = (command or "").strip().lower()
    raw_device = (device or "").strip().lower()

    if raw_command in ALLOWED_COMMANDS:
        return raw_command
    if raw_command == "":
        return "none"

    mapped = LEGACY_COMMAND_MAP.get((raw_device, raw_command))
    if mapped:
        return mapped

    raise HTTPException(status_code=400, detail=f"不支持的指令: {device or ''} {command or ''}".strip())


def create_command(db: Session, payload: CommandCreate) -> DeviceCommand:
    command_name = normalize_command(payload.device, payload.command)
    command = DeviceCommand(
        command=command_name,
        parameter=payload.parameter or payload.value,
        status="pending",
        source=payload.source or "frontend",
        confidence=payload.confidence,
        raw_payload=payload.model_dump(),
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def create_cloud_command_record(db: Session, response: CloudCommandResponse) -> Optional[DeviceCommand]:
    if response.command == "none":
        return None
    command = DeviceCommand(
        command=response.command,
        parameter=response.parameter or None,
        status="generated",
        source="cloud",
        confidence=response.confidence,
        reason=response.reason,
        raw_payload=response.model_dump(),
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def get_oldest_pending_command(db: Session) -> Optional[DeviceCommand]:
    return db.scalars(
        select(DeviceCommand)
        .where(DeviceCommand.status == "pending")
        .order_by(DeviceCommand.id.asc())
        .limit(1)
    ).first()


def ack_command(db: Session, command_id: int) -> Optional[DeviceCommand]:
    command = db.get(DeviceCommand, command_id)
    if command is None or command.status != "pending":
        return None
    command.status = "executed"
    command.executed_at = datetime.utcnow()
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def validate_cloud_command(command: str, allowed_commands: list[str]) -> str:
    normalized_allowed = set(allowed_commands or [])
    if not normalized_allowed:
        normalized_allowed = ALLOWED_COMMANDS
    if "none" not in normalized_allowed:
        normalized_allowed.add("none")
    if command not in ALLOWED_COMMANDS or command not in normalized_allowed:
        return "none"
    return command
