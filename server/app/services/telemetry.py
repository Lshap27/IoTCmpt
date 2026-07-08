from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models
from app.schemas import CommandAckIn, TelemetryIn
from app.services.commands import ensure_device


def naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def record_status(db: Session, device_id: str, status: str, raw_payload: dict | None = None) -> models.Device:
    device = ensure_device(db, device_id)
    device.status = status
    device.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
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


BUCKETED_HISTORY_SQL = text(
    """
    SELECT
        time_bucket(make_interval(secs => :bucket), sampled_at) AS bucket,
        avg(temperature_c) AS temperature_c,
        avg(humidity_percent) AS humidity_percent,
        avg(tvoc_ppb) AS tvoc_ppb,
        avg(hcho_ug_m3) AS hcho_ug_m3,
        avg(eco2_ppm) AS eco2_ppm,
        bool_or(window_open) AS window_open,
        bool_or(alarm_on) AS alarm_on,
        CASE max(CASE air_quality WHEN 'alert' THEN 3 WHEN 'watch' THEN 2 WHEN 'good' THEN 1 ELSE 0 END)
            WHEN 3 THEN 'alert' WHEN 2 THEN 'watch' WHEN 1 THEN 'good' ELSE 'unknown'
        END AS air_quality,
        count(*) AS sample_count
    FROM telemetry
    WHERE device_id = :device_id
    GROUP BY bucket
    ORDER BY bucket DESC
    LIMIT :limit
    """
)


def fetch_history_bucketed(db: Session, device_id: str, bucket_seconds: int, limit: int) -> list[dict]:
    """time_bucket 降采样查询；仅在 PostgreSQL/TimescaleDB 上可用。"""
    rows = db.execute(
        BUCKETED_HISTORY_SQL,
        {"bucket": bucket_seconds, "device_id": device_id, "limit": limit},
    ).mappings()
    return [
        {
            "bucket": row["bucket"].isoformat(),
            "temperature_c": row["temperature_c"],
            "humidity_percent": row["humidity_percent"],
            "tvoc_ppb": row["tvoc_ppb"],
            "hcho_ug_m3": row["hcho_ug_m3"],
            "eco2_ppm": row["eco2_ppm"],
            "window_open": row["window_open"],
            "alarm_on": row["alarm_on"],
            "air_quality": row["air_quality"],
            "sample_count": row["sample_count"],
        }
        for row in rows
    ]
