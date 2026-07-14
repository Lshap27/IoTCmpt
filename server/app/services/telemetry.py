from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import CommandAckIn, TelemetryIn
from app.services.commands import ensure_device

COMMAND_STATUS_ORDER = {
    "created": 0,
    "pending": 0,
    "queued": 1,
    "published": 2,
    "accepted": 3,
    "executed": 4,
    "rejected": 4,
    "failed": 4,
    "expired": 4,
    "timed_out": 4,
}


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
        smoke_detected=payload.sensors.smoke_detected,
        window_open=payload.state.window_open,
        alarm_on=payload.state.alarm_on,
        manual_override=payload.state.manual_override,
        manual_window_override=payload.state.manual_window_override,
        manual_led_override=payload.state.manual_led_override,
        control_priority=payload.state.control_priority,
        smoke_silenced=payload.state.smoke_silenced,
        led_on=payload.state.led_on,
        air_quality=payload.fusion.air_quality,
        recommend_open_window=payload.fusion.recommend_open_window,
        alarm_enabled=payload.fusion.alarm_enabled,
        reason=payload.fusion.reason,
        raw_payload=payload.model_dump(mode="json"),
    )
    db.add(sample)
    twin = db.query(models.DeviceTwin).filter(models.DeviceTwin.device_id == payload.device_id).one_or_none()
    if twin is None:
        twin = models.DeviceTwin(device_id=payload.device_id, desired_state={}, reported_state={})
    twin.reported_state = payload.state.model_dump(mode="json", exclude_none=True)
    twin.reported_at = naive_utc(payload.sampled_at)
    db.add(twin)
    db.commit()
    db.refresh(sample)
    return sample


def record_command_ack(db: Session, payload: CommandAckIn) -> models.Command | None:
    command = db.query(models.Command).filter(models.Command.command_id == payload.command_id).one_or_none()
    if command is None:
        return None
    current_rank = COMMAND_STATUS_ORDER.get(command.status, -1)
    incoming_rank = COMMAND_STATUS_ORDER.get(payload.status, -1)
    if incoming_rank <= current_rank:
        return command
    previous = command.status
    command.status = payload.status
    command.error_code = payload.error_code
    if payload.status == "accepted":
        command.accepted_at = naive_utc(payload.executed_at)
    else:
        command.executed_at = naive_utc(payload.executed_at)
    db.add(
        models.CommandEvent(
            command_id=command.command_id,
            trace_id=payload.trace_id or command.trace_id,
            from_status=previous,
            to_status=payload.status,
            error_code=payload.error_code,
            detail={"message": payload.message, "reported_state": payload.reported_state},
        )
    )
    if payload.reported_state:
        twin = db.query(models.DeviceTwin).filter(models.DeviceTwin.device_id == payload.device_id).one_or_none()
        if twin is None:
            twin = models.DeviceTwin(device_id=payload.device_id, desired_state={}, reported_state={})
        twin.reported_state = {**(twin.reported_state or {}), **payload.reported_state}
        twin.reported_at = naive_utc(payload.executed_at)
        db.add(twin)
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def serialize_telemetry(sample: models.Telemetry) -> dict:
    return {
        "device_id": sample.device_id,
        "sampled_at": iso_utc(sample.sampled_at),
        "sensors": {
            "temperature_c": sample.temperature_c,
            "humidity_percent": sample.humidity_percent,
            "tvoc_ppb": sample.tvoc_ppb,
            "hcho_ug_m3": sample.hcho_ug_m3,
            "eco2_ppm": sample.eco2_ppm,
            "light_is_dark": sample.light_is_dark,
            "smoke_detected": sample.smoke_detected,
        },
        "state": {
            "window_open": sample.window_open,
            "alarm_on": sample.alarm_on,
            "manual_override": sample.manual_override,
            "manual_window_override": sample.manual_window_override,
            "manual_led_override": sample.manual_led_override,
            "control_priority": sample.control_priority,
            "smoke_silenced": sample.smoke_silenced,
            "led_on": sample.led_on,
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
        min(temperature_c) AS temperature_min_c,
        max(temperature_c) AS temperature_max_c,
        avg(humidity_percent) AS humidity_percent,
        min(humidity_percent) AS humidity_min_percent,
        max(humidity_percent) AS humidity_max_percent,
        avg(tvoc_ppb) AS tvoc_ppb,
        avg(hcho_ug_m3) AS hcho_ug_m3,
        avg(eco2_ppm) AS eco2_ppm,
        max(eco2_ppm) AS eco2_max_ppm,
        bool_or(light_is_dark) AS light_is_dark,
        bool_or(smoke_detected) AS smoke_detected,
        bool_or(window_open) AS window_open,
        bool_or(alarm_on) AS alarm_on,
        bool_or(led_on) AS led_on,
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
            "bucket": iso_utc(row["bucket"]),
            "temperature_c": row["temperature_c"],
            "temperature_min_c": row["temperature_min_c"],
            "temperature_max_c": row["temperature_max_c"],
            "humidity_percent": row["humidity_percent"],
            "humidity_min_percent": row["humidity_min_percent"],
            "humidity_max_percent": row["humidity_max_percent"],
            "tvoc_ppb": row["tvoc_ppb"],
            "hcho_ug_m3": row["hcho_ug_m3"],
            "eco2_ppm": row["eco2_ppm"],
            "eco2_max_ppm": row["eco2_max_ppm"],
            "light_is_dark": row["light_is_dark"],
            "smoke_detected": row["smoke_detected"],
            "window_open": row["window_open"],
            "alarm_on": row["alarm_on"],
            "led_on": row["led_on"],
            "air_quality": row["air_quality"],
            "sample_count": row["sample_count"],
        }
        for row in rows
    ]
