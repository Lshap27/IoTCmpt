from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.schemas import CommandAckIn, TelemetryIn
from app.services.commands import ensure_device


def naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def record_status(db: Session, device_id: str, status: str, raw_payload: dict | None = None) -> models.Device:
    device = ensure_device(db, device_id)
    device.status = status
    device.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    device.meta = raw_payload or device.meta
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def record_telemetry(db: Session, payload: TelemetryIn) -> models.Telemetry:
    record_status(db, payload.device_id, "online")
    sample = models.Telemetry(
        device_id=payload.device_id,
        sampled_at=naive_utc(payload.sampled_at),
        temperature_c=payload.sensors.temperature_c,
        humidity_percent=payload.sensors.humidity_percent,
        tvoc_ppb=payload.sensors.tvoc_ppb,
        hcho_ug_m3=payload.sensors.hcho_ug_m3,
        eco2_ppm=payload.sensors.eco2_ppm,
        light_is_dark=payload.sensors.light_is_dark,
        window_open=payload.state.window_open,
        alarm_on=payload.state.alarm_on,
        manual_override=payload.state.manual_override,
        air_quality=payload.fusion.air_quality,
        recommend_open_window=payload.fusion.recommend_open_window,
        alarm_enabled=payload.fusion.alarm_enabled,
        reason=payload.fusion.reason,
        raw_payload=payload.model_dump(mode="json"),
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


def record_command_ack(db: Session, payload: CommandAckIn) -> models.Command | None:
    command = db.query(models.Command).filter(models.Command.command_id == payload.command_id).one_or_none()
    if command is None:
        return None
    command.status = payload.status
    command.executed_at = naive_utc(payload.executed_at)
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def serialize_telemetry(sample: models.Telemetry) -> dict:
    return {
        "device_id": sample.device_id,
        "sampled_at": sample.sampled_at.isoformat(),
        "sensors": {
            "temperature_c": sample.temperature_c,
            "humidity_percent": sample.humidity_percent,
            "tvoc_ppb": sample.tvoc_ppb,
            "hcho_ug_m3": sample.hcho_ug_m3,
            "eco2_ppm": sample.eco2_ppm,
            "light_is_dark": sample.light_is_dark,
        },
        "state": {
            "window_open": sample.window_open,
            "alarm_on": sample.alarm_on,
            "manual_override": sample.manual_override,
        },
        "fusion": {
            "air_quality": sample.air_quality,
            "recommend_open_window": sample.recommend_open_window,
            "alarm_enabled": sample.alarm_enabled,
            "reason": sample.reason,
        },
    }

