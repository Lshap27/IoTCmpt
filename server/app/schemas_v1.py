from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AutomationPredicateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: Literal[
        "light_is_dark",
        "human_present",
        "air_quality",
        "temperature_c",
        "humidity_percent",
        "tvoc_ppb",
        "hcho_ug_m3",
        "eco2_ppm",
        "window_open",
        "led_on",
        "device_status",
    ]
    op: Literal["eq", "in", "gt", "gte", "lt", "lte"]
    value: Any


class AutomationConditionTriggerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["condition"]
    mode: Literal["all", "any"]
    items: list[AutomationPredicateIn] = Field(min_length=1, max_length=8)
    stability_samples: int = Field(ge=1, le=5)


class AutomationIntervalTriggerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["interval"]
    every_seconds: int = Field(ge=60, le=86400)


AutomationTriggerIn = Annotated[
    AutomationConditionTriggerIn | AutomationIntervalTriggerIn,
    Field(discriminator="type"),
]


class AutomationActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["window.open", "window.close", "led.on", "led.off", "voice.speak", "display.message"]
    parameter: dict[str, Any]
    text: str | None = Field(default=None, min_length=1, max_length=120)


class AutomationRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    description: str = Field(min_length=1, max_length=240)
    trigger: AutomationTriggerIn
    action: AutomationActionIn
    cooldown_seconds: int = Field(ge=0, le=86400)


class AutomationPlanSpecV1In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    title: str = Field(min_length=1, max_length=120)
    duration_seconds: int = Field(ge=60, le=86400)
    timezone: str = Field(min_length=1, max_length=64)
    manual_override_policy: Literal["respect"]
    end_behavior: Literal["keep_state"]
    clarifications: list[str] = Field(max_length=5)
    rules: list[AutomationRuleIn] = Field(min_length=1, max_length=16)


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
    patrol_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    patrol_force_interval_seconds: int | None = Field(default=None, ge=5, le=604800)
    vision_schedule_enabled: bool | None = None
    vision_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    sedentary_trigger_enabled: bool | None = None
    sedentary_threshold_seconds: int | None = Field(default=None, ge=5, le=86400)
    strategy_enabled: bool | None = None
    strategy_min_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    strategy_force_interval_seconds: int | None = Field(default=None, ge=5, le=604800)
    execution_mode: Literal["automatic"] | None = None

    @model_validator(mode="after")
    def check_intervals(self):
        if (
            self.patrol_interval_seconds is not None
            and self.patrol_force_interval_seconds is not None
            and self.patrol_force_interval_seconds < self.patrol_interval_seconds
        ):
            raise ValueError("patrol_force_interval_seconds must be at least patrol_interval_seconds")
        if (
            self.strategy_min_interval_seconds is not None
            and self.strategy_force_interval_seconds is not None
            and self.strategy_force_interval_seconds < self.strategy_min_interval_seconds
        ):
            raise ValueError("strategy_force_interval_seconds must be at least strategy_min_interval_seconds")
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
    strategy_enabled: bool
    strategy_min_interval_seconds: int
    strategy_force_interval_seconds: int
    execution_mode: Literal["automatic"]
    thresholds: dict[str, float]
    last_checked_at: str | None = None
    last_model_run_at: str | None = None
    last_strategy_run_at: str | None = None


class AiRunCreate(BaseModel):
    kind: Literal["decision", "report", "vision", "patrol", "plan_compile", "strategy"]
    trigger: Literal["manual", "event", "schedule", "patrol"] = "manual"
    goal: str = Field(default="", max_length=1000)
    period: Literal["hour", "day", "week"] | None = None
    image_id: int | None = None
    plan_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def check_kind_payload(self):
        if self.kind == "report" and self.period is None:
            raise ValueError("report runs require period")
        if self.kind != "report" and self.period is not None:
            raise ValueError("period is only valid for report runs")
        if self.kind == "plan_compile" and not self.goal.strip():
            raise ValueError("plan_compile runs require a non-empty goal")
        if self.plan_id is not None and self.kind != "strategy":
            raise ValueError("plan_id is only valid for strategy runs")
        return self


class AutomationRuleStateOut(BaseModel):
    rule_id: str
    last_condition: str
    last_fired_at: str | None = None
    next_fire_at: str | None = None
    last_command_id: str | None = None
    blocked_reason: str | None = None


class AutomationPlanOut(BaseModel):
    plan_id: str
    device_id: str
    plan_type: Literal["system", "user"]
    title: str
    status: Literal["draft", "active", "paused", "completed", "cancelled", "failed", "superseded"]
    current_version: int
    source_prompt: str
    activation_blockers: list[str]
    spec: dict[str, Any]
    explanation: str
    validation: dict[str, Any]
    rule_states: list[AutomationRuleStateOut]
    started_at: str | None = None
    paused_at: str | None = None
    ends_at: str | None = None
    completed_at: str | None = None
    created_at: str
    updated_at: str


class AutomationPlanEventOut(BaseModel):
    event_id: str
    plan_id: str
    device_id: str
    version: int
    rule_id: str | None = None
    trace_id: str | None = None
    event_type: str
    detail: dict[str, Any]
    occurred_at: str


class AutomationPlanActivateIn(BaseModel):
    replace_active: bool = False


class AiStrategyOut(BaseModel):
    strategy_id: str
    device_id: str
    run_id: str
    plan_id: str | None = None
    base_version: int | None = None
    proposed_spec: dict[str, Any]
    diff: list[dict[str, Any]]
    summary: str
    status: Literal["proposed", "approved", "rejected", "skipped"]
    created_at: str
    resolved_at: str | None = None


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
