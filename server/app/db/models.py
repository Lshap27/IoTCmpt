from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    manual_window_override: Mapped[bool | None] = mapped_column(Boolean)
    manual_led_override: Mapped[bool | None] = mapped_column(Boolean)
    control_priority: Mapped[str | None] = mapped_column(String(32))
    smoke_silenced: Mapped[bool | None] = mapped_column(Boolean)
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
    __table_args__ = (UniqueConstraint("device_id", "source", "idempotency_key", name="uq_command_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    parameter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="frontend")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    voice_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_command_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("commands.command_id", ondelete="SET NULL"), unique=True, index=True
    )
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


class DeviceCapability(Base):
    __tablename__ = "device_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), unique=True, index=True)
    protocol_version: Mapped[str] = mapped_column(String(16), default="2.0")
    firmware_version: Mapped[str] = mapped_column(String(64), default="unknown")
    hardware_model: Mapped[str] = mapped_column(String(64), default="ESP32-S3")
    commands: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    capability_hash: Mapped[str] = mapped_column(String(64), default="")
    seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DeviceTwin(Base):
    __tablename__ = "device_twins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), unique=True, index=True)
    desired_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reported_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    desired_at: Mapped[datetime | None] = mapped_column(DateTime)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime)


class CommandEvent(Base):
    __tablename__ = "command_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), ForeignKey("commands.command_id"), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), ForeignKey("commands.command_id"), unique=True, index=True)
    topic: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    qos: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(96), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="manual")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(128), default="")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(96), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiToolCall(Base):
    __tablename__ = "ai_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("ai_runs.run_id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="started", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AutomationPolicy(Base):
    __tablename__ = "automation_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    event_trigger_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    patrol_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    patrol_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    patrol_force_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    vision_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    vision_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    sedentary_trigger_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sedentary_threshold_seconds: Mapped[int] = mapped_column(Integer, default=7200)
    execution_mode: Mapped[str] = mapped_column(String(24), default="automatic")
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_fingerprint: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_model_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AiReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (UniqueConstraint("run_id", name="uq_ai_reports_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("ai_runs.run_id"), index=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    period: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class RealtimeEvent(Base):
    __tablename__ = "realtime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(96), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("devices.device_id"), index=True)
    component: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class RuntimeInstance(Base):
    __tablename__ = "runtime_instances"

    instance_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RuntimeLease(Base):
    __tablename__ = "runtime_leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(96), index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
