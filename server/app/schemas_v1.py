from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CapabilityCommandOut(BaseModel):
    name: str
    parameter_schema: dict[str, Any]
    safety_class: Literal["normal", "safety", "administrative"]
    ai_allowed: bool = False


class DeviceCapabilitiesOut(BaseModel):
    device_id: str
    protocol_version: str
    firmware_version: str
    hardware_model: str
    commands: list[CapabilityCommandOut]
    seen_at: str | None = None


class CommandCreateV1(BaseModel):
    type: str
    parameter: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    expires_at: datetime | None = None


class CommandV1Out(BaseModel):
    command_id: str
    trace_id: str
    device_id: str
    type: str
    parameter: dict[str, Any]
    source: str
    reason: str
    status: str
    error_code: str | None = None
    created_at: str
    expires_at: str | None = None
    published_at: str | None = None
    accepted_at: str | None = None
    completed_at: str | None = None
    capability: dict[str, Any] | None = None


class AutomationPolicyIn(BaseModel):
    enabled: bool | None = None
    event_trigger_enabled: bool | None = None
    patrol_enabled: bool | None = None
    patrol_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    patrol_force_interval_seconds: int | None = Field(default=None, ge=300, le=604800)
    vision_schedule_enabled: bool | None = None
    vision_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    sedentary_trigger_enabled: bool | None = None
    sedentary_threshold_seconds: int | None = Field(default=None, ge=300, le=86400)
    execution_mode: Literal["automatic"] | None = None

    @model_validator(mode="after")
    def check_intervals(self):
        if (
            self.patrol_interval_seconds is not None
            and self.patrol_force_interval_seconds is not None
            and self.patrol_force_interval_seconds < self.patrol_interval_seconds
        ):
            raise ValueError("patrol_force_interval_seconds must be at least patrol_interval_seconds")
        return self


class AutomationPolicyOut(BaseModel):
    device_id: str
    enabled: bool
    event_trigger_enabled: bool
    patrol_enabled: bool
    patrol_interval_seconds: int
    patrol_force_interval_seconds: int
    vision_schedule_enabled: bool
    vision_interval_seconds: int
    sedentary_trigger_enabled: bool
    sedentary_threshold_seconds: int
    execution_mode: Literal["automatic"]
    thresholds: dict[str, float]
    last_checked_at: str | None = None
    last_model_run_at: str | None = None


class AiRunCreate(BaseModel):
    kind: Literal["decision", "report", "vision", "patrol"]
    trigger: Literal["manual", "event", "schedule", "patrol"] = "manual"
    goal: str = Field(default="", max_length=1000)
    period: Literal["hour", "day", "week"] | None = None
    image_id: int | None = None

    @model_validator(mode="after")
    def check_kind_payload(self):
        if self.kind == "report" and self.period is None:
            raise ValueError("report runs require period")
        if self.kind != "report" and self.period is not None:
            raise ValueError("period is only valid for report runs")
        return self


class AiRunOut(BaseModel):
    run_id: str
    trace_id: str
    device_id: str
    kind: str
    trigger: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    model: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    cancel_requested_at: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class TraceEventOut(BaseModel):
    event_id: str
    device_id: str | None = None
    component: str
    event_type: str
    status: str | None = None
    detail: dict[str, Any]
    occurred_at: str


class TraceTimelineOut(BaseModel):
    trace_id: str
    events: list[TraceEventOut] = Field(default_factory=list)
