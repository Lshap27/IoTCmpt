from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    temperature_in: Mapped[Optional[float]] = mapped_column(Float)
    humidity_in: Mapped[Optional[float]] = mapped_column(Float)
    temperature_out: Mapped[Optional[float]] = mapped_column(Float)
    humidity_out: Mapped[Optional[float]] = mapped_column(Float)
    co2: Mapped[Optional[float]] = mapped_column(Float)
    tvoc: Mapped[Optional[float]] = mapped_column(Float)
    hcho: Mapped[Optional[float]] = mapped_column(Float)
    light: Mapped[Optional[int]] = mapped_column(Integer)
    led_status: Mapped[Optional[str]] = mapped_column(String(16))
    window_status: Mapped[Optional[str]] = mapped_column(String(16))
    dehumidifier_state: Mapped[Optional[str]] = mapped_column(String(16))
    air_quality: Mapped[Optional[str]] = mapped_column(String(32))
    recommend_open_window: Mapped[Optional[bool]] = mapped_column(Integer)
    alarm_enabled: Mapped[Optional[bool]] = mapped_column(Integer)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PoseEvent(Base):
    __tablename__ = "pose_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pose: Mapped[str] = mapped_column(String(128))
    human_presence: Mapped[str] = mapped_column(String(16), default="unknown")
    image_url: Mapped[Optional[str]] = mapped_column(String(512))
    pose_image_url: Mapped[Optional[str]] = mapped_column(String(512))
    photo_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DeviceCommand(Base):
    __tablename__ = "device_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    command: Mapped[str] = mapped_column(String(64), index=True)
    parameter: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(32), default="frontend")
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    @property
    def legacy_device_command(self) -> tuple[str, str]:
        if self.command.startswith("window."):
            return "window", self.command.split(".", 1)[1]
        if self.command.startswith("alarm."):
            return "alarm", self.command.split(".", 1)[1]
        return "unknown", self.command
