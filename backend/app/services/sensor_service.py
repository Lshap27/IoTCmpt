from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PoseEvent, SensorReading
from app.schemas import SensorUpload


def _format_time(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def create_sensor_reading(db: Session, data: SensorUpload) -> SensorReading:
    reading = SensorReading(
        temperature_in=data.temperature_in,
        humidity_in=data.humidity_in,
        temperature_out=data.temperature_out,
        humidity_out=data.humidity_out,
        co2=data.co2,
        tvoc=data.tvoc,
        hcho=data.hcho,
        light=data.light,
        air_quality=data.air_quality,
        recommend_open_window=data.recommend_open_window,
        alarm_enabled=data.alarm_enabled,
        reason=data.reason,
        raw_payload=data.model_dump(),
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


def latest_sensor_reading(db: Session) -> Optional[SensorReading]:
    return db.scalars(select(SensorReading).order_by(SensorReading.sampled_at.desc(), SensorReading.id.desc()).limit(1)).first()


def latest_pose_event(db: Session) -> Optional[PoseEvent]:
    return db.scalars(select(PoseEvent).order_by(PoseEvent.photo_time.desc(), PoseEvent.id.desc()).limit(1)).first()


def reading_payload(reading: Optional[SensorReading], pose: Optional[PoseEvent]) -> Optional[Dict[str, Any]]:
    if reading is None and pose is None:
        return None
    return {
        "temperature_in": reading.temperature_in if reading else None,
        "humidity_in": reading.humidity_in if reading else None,
        "temperature_out": reading.temperature_out if reading else None,
        "humidity_out": reading.humidity_out if reading else None,
        "co2": reading.co2 if reading else None,
        "tvoc": reading.tvoc if reading else None,
        "hcho": reading.hcho if reading else None,
        "light": reading.light if reading else None,
        "air_quality": reading.air_quality if reading else None,
        "recommend_open_window": reading.recommend_open_window if reading else None,
        "alarm_enabled": reading.alarm_enabled if reading else None,
        "reason": reading.reason if reading else None,
        "human_presence": pose.human_presence if pose else "unknown",
        "time": _format_time(reading.sampled_at if reading else None),
        "pose": pose.pose if pose else None,
        "image_url": pose.image_url if pose else None,
        "pose_image_url": pose.pose_image_url if pose else None,
        "photo_time": _format_time(pose.photo_time if pose else None),
    }


def latest_payload(db: Session) -> Optional[Dict[str, Any]]:
    return reading_payload(latest_sensor_reading(db), latest_pose_event(db))


def list_history_payloads(db: Session, limit: int) -> list[Dict[str, Any]]:
    pose = latest_pose_event(db)
    readings = db.scalars(
        select(SensorReading).order_by(SensorReading.sampled_at.desc(), SensorReading.id.desc()).limit(limit)
    ).all()
    return [reading_payload(reading, pose) for reading in readings]


def summary_payload(db: Session) -> Optional[Dict[str, Any]]:
    payload = latest_payload(db)
    if payload is None:
        return None
    presence = payload.get("human_presence")
    payload["status"] = "有人" if presence == "yes" else "无人" if presence == "no" else "未知"
    return payload
