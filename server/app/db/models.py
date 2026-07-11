from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Telemetry(Base):
    __tablename__ = "telemetry"

    # On PostgreSQL the actual primary key is (id, sampled_at) — required by the
    # TimescaleDB hypertable and managed by migration 0002. The ORM keeps the
    # single-column id so SQLite test databases still autoincrement.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_percent: Mapped[float | None] = mapped_column(Float)
    tvoc_ppb: Mapped[float | None] = mapped_column(Float)
    hcho_ug_m3: Mapped[float | None] = mapped_column(Float)
    eco2_ppm: Mapped[float | None] = mapped_column(Float)
    light_is_dark: Mapped[bool | None] = mapped_column(Boolean)
    smoke_detected: Mapped[bool | None] = mapped_column(Boolean)
    window_open: Mapped[bool | None] = mapped_column(Boolean)
    alarm_on: Mapped[bool | None] = mapped_column(Boolean)
    manual_override: Mapped[bool | None] = mapped_column(Boolean)
    led_on: Mapped[bool | None] = mapped_column(Boolean)
    air_quality: Mapped[str | None] = mapped_column(String(32))
    recommend_open_window: Mapped[bool | None] = mapped_column(Boolean)
    alarm_enabled: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DeviceEvent(Base):
    __tablename__ = "device_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    parameter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="frontend")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiResult(Base):
    __tablename__ = "ai_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    command_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String(32), default="unknown")
    model: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128), default="image/jpeg")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32), default="capture", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PoseResult(Base):
    __tablename__ = "pose_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    source_image_id: Mapped[int] = mapped_column(Integer, ForeignKey("image_assets.id"), index=True)
    annotated_image_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("image_assets.id"))
    human_present: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
