from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CommandType = Literal[
    "none",
    "window.open",
    "window.close",
    "alarm.on",
    "alarm.off",
    "led.on",
    "led.off",
    "control.set_priority",
    "control.resume_auto",
    "alarm.silence",
    "voice.speak",
    "display.message",
]
CommandSource = Literal["frontend", "llm", "rule"]
PresenceSource = Literal["object_detector", "pose_fallback", "none", "error"]
BodyCoverage = Literal["upper_body", "full_body", "insufficient"]
SeatedState = Literal["seated", "not_seated", "unknown"]
PostureCode = Literal["upright", "forward_lean", "hunched", "head_down", "not_seated", "unknown"]
PostureIssue = Literal["forward_lean", "hunched", "head_down"]


class SensorPayload(BaseModel):
    temperature_c: float | None = None
    humidity_percent: float | None = None
    tvoc_ppb: float | None = None
    hcho_ug_m3: float | None = None
    eco2_ppm: float | None = None
    light_is_dark: bool | None = None
    smoke_detected: bool | None = None


class DeviceStatePayload(BaseModel):
    window_open: bool | None = None
    alarm_on: bool | None = None
    manual_override: bool | None = None
    manual_window_override: bool | None = None
    manual_led_override: bool | None = None
    control_priority: Literal["manual_first", "auto_first"] | None = None
    smoke_silenced: bool | None = None
    led_on: bool | None = None


class FusionPayload(BaseModel):
    air_quality: Literal["good", "watch", "alert", "unknown"] = "unknown"
    recommend_open_window: bool = False
    alarm_enabled: bool = False
    reason: str = ""


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    device_id: str
    sampled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sensors: SensorPayload = Field(default_factory=SensorPayload)
    state: DeviceStatePayload = Field(default_factory=DeviceStatePayload)
    fusion: FusionPayload = Field(default_factory=FusionPayload)


class CommandIn(BaseModel):
    type: CommandType
    parameter: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


VoiceStatus = Literal["not_requested", "unavailable", "pending", "executed", "rejected", "failed"]


class NotificationIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    voice_broadcast: bool = False

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("notification content must not be blank")
        return value

    @model_validator(mode="after")
    def validate_voice_payload_size(self) -> Self:
        if self.voice_broadcast and len(self.content.encode("gb2312", errors="replace")) > 220:
            raise ValueError("voice notification exceeds the SYN6288 220-byte GB2312 limit")
        return self


class CommandMessage(BaseModel):
    command_id: str = Field(default_factory=lambda: f"cmd-{uuid4().hex[:16]}")
    type: CommandType
    parameter: dict[str, Any] = Field(default_factory=dict)
    source: CommandSource = "frontend"
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CommandAckIn(BaseModel):
    device_id: str
    command_id: str
    status: Literal["executed", "rejected", "failed"]
    message: str = ""
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AiAnalyzeResponse(CommandMessage):
    pass


RiskLevel = Literal["low", "medium", "high", "unknown"]


class AiDecision(BaseModel):
    command: CommandMessage
    risk_level: RiskLevel = "unknown"
    summary: str = ""
    model: str = ""
    speech: str = ""
    scene_summary: str = ""


class AutopilotIn(BaseModel):
    enabled: bool | None = None
    vision_interval_enabled: bool | None = None
    vision_interval_seconds: float | None = Field(default=None, ge=30, le=3600)
    sedentary_threshold_seconds: float | None = Field(default=None, ge=5, le=28800)
    smoke_silence_seconds: int | None = Field(default=None, ge=10, le=600)


class ImageAssetOut(BaseModel):
    id: int
    device_id: str
    url: str
    created_at: datetime


class EventOut(BaseModel):
    id: int
    device_id: str
    type: str
    severity: str
    message: str
    acknowledged_at: str | None = None
    created_at: str


class PoseResultOut(BaseModel):
    id: int
    device_id: str
    human_present: bool
    label: str
    confidence: float
    presence_confidence: float
    presence_source: PresenceSource
    body_coverage: BodyCoverage
    seated_state: SeatedState
    posture_code: PostureCode
    posture_issues: list[PostureIssue]
    posture_confidence: float
    posture_fresh: bool
    source_image_url: str
    annotated_image_url: str | None = None
    created_at: str


class PoseAnalyzeAccepted(BaseModel):
    queued: bool
    source_image_id: int


class WebSocketEnvelope(BaseModel):
    type: str
    device_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


# ---- HTTP 响应模型（OpenAPI 单一事实来源）----
# 字段与 services 层的 serialize_* 输出逐一对应；时间字段凡是序列化器手工
# isoformat 的地方声明为 str，保持线上格式不变。


class HealthOut(BaseModel):
    status: str
    service: str


class DeviceSummary(BaseModel):
    device_id: str
    display_name: str
    status: str
    last_seen_at: str | None = None


class FusionSnapshot(BaseModel):
    air_quality: str | None = None
    recommend_open_window: bool | None = None
    alarm_enabled: bool | None = None
    reason: str | None = None


class TelemetryPoint(BaseModel):
    device_id: str
    sampled_at: str
    sensors: SensorPayload
    state: DeviceStatePayload
    fusion: FusionSnapshot


class TelemetryBucketPoint(BaseModel):
    """time_bucket 降采样后的遥测聚合点（数值取均值，布尔取或，air_quality 取最差档）。"""

    bucket: str
    temperature_c: float | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    humidity_percent: float | None = None
    humidity_min_percent: float | None = None
    humidity_max_percent: float | None = None
    tvoc_ppb: float | None = None
    hcho_ug_m3: float | None = None
    eco2_ppm: float | None = None
    eco2_max_ppm: float | None = None
    light_is_dark: bool | None = None
    smoke_detected: bool | None = None
    window_open: bool | None = None
    alarm_on: bool | None = None
    led_on: bool | None = None
    air_quality: str | None = None
    sample_count: int


class CommandOut(BaseModel):
    command_id: str
    type: str
    parameter: dict[str, Any] = Field(default_factory=dict)
    source: str
    confidence: float
    reason: str
    status: str
    created_at: str
    published_at: str | None = None
    executed_at: str | None = None


class NotificationOut(BaseModel):
    id: int
    device_id: str
    content: str
    voice_requested: bool
    voice_command_id: str | None = None
    voice_status: VoiceStatus
    created_at: str


class ImageSnapshot(BaseModel):
    id: int
    url: str
    created_at: str


class PoseSnapshot(BaseModel):
    id: int
    human_present: bool
    label: str
    confidence: float
    presence_confidence: float
    presence_source: PresenceSource
    body_coverage: BodyCoverage
    seated_state: SeatedState
    posture_code: PostureCode
    posture_issues: list[PostureIssue]
    posture_confidence: float
    posture_fresh: bool
    source_image_url: str
    annotated_image_url: str | None = None
    created_at: str


class AiResultInfo(BaseModel):
    command_id: str
    risk_level: str
    confidence: float
    reason: str
    summary: str
    model: str
    speech: str = ""
    scene_summary: str = ""


class AutopilotEnabled(BaseModel):
    enabled: bool
    vision_capability: Literal["unknown", "supported", "unsupported"] = "unknown"
    vision_interval_enabled: bool = False
    vision_interval_seconds: float = 300
    sedentary_threshold_seconds: float = 7200
    smoke_silence_seconds: int = 60


class AutopilotState(BaseModel):
    device_id: str
    enabled: bool
    cooldown_seconds: float
    min_confidence: float
    trigger_levels: list[str] = Field(
        description="Deprecated: 空气质量与烟雾自动规则已移至固件；保留此字段仅用于兼容旧客户端。",
        json_schema_extra={"deprecated": True},
    )
    vision_capability: Literal["unknown", "supported", "unsupported"]
    vision_interval_enabled: bool
    vision_interval_effective: bool
    vision_interval_seconds: float
    sedentary_threshold_seconds: float
    smoke_silence_seconds: int


class LatestState(BaseModel):
    device: DeviceSummary
    telemetry: TelemetryPoint | None = None
    image: ImageSnapshot | None = None
    pose: PoseSnapshot | None = None
    command: CommandOut | None = None
    ai_result: AiResultInfo | None = None
    autopilot: AutopilotEnabled | None = None


class AiDecisionOut(BaseModel):
    command: CommandOut
    risk_level: RiskLevel
    confidence: float
    reason: str
    model: str
    trigger: str
    published: bool
    speech: str = ""
    scene_summary: str = ""


ReportPeriod = Literal["hour", "day", "week"]


class AiReportIn(BaseModel):
    period: ReportPeriod = "day"


class ReportCoverage(BaseModel):
    start: str
    end: str
    sample_count: int
    bucket_count: int
    expected_bucket_count: int
    completeness_percent: float


class ReportMetrics(BaseModel):
    temperature_avg_c: float | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    humidity_avg_percent: float | None = None
    tvoc_avg_ppb: float | None = None
    hcho_avg_ug_m3: float | None = None
    eco2_avg_ppm: float | None = None
    eco2_max_ppm: float | None = None
    alert_bucket_count: int = 0
    smoke_event_count: int = 0


class AiHealthReport(BaseModel):
    device_id: str
    period: ReportPeriod
    generated_at: str
    model: str
    risk_level: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    headline: str
    summary: str
    anomalies: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    coverage: ReportCoverage
    metrics: ReportMetrics


# ---- WebSocket envelope 判别联合 ----
# 仅用于协议契约（导出到 openapi.json 供前端 codegen），运行时广播仍走
# WebSocketEnvelope；type 字段是判别键，前端 switch 后 payload 自动窄化。


class _EnvelopeBase(BaseModel):
    device_id: str
    occurred_at: datetime


class TelemetryEnvelope(_EnvelopeBase):
    type: Literal["telemetry"]
    payload: TelemetryPoint


class StatusPayload(BaseModel):
    device_id: str
    status: str
    last_seen_at: str | None = None


class StatusEnvelope(_EnvelopeBase):
    type: Literal["status"]
    payload: StatusPayload


class ImageEnvelope(_EnvelopeBase):
    type: Literal["image"]
    payload: ImageSnapshot


class PoseEnvelope(_EnvelopeBase):
    type: Literal["pose_result"]
    payload: PoseResultOut


class CommandEnvelope(_EnvelopeBase):
    type: Literal["command"]
    payload: CommandOut


class NotificationEnvelope(_EnvelopeBase):
    type: Literal["notification"]
    payload: NotificationOut


class CommandAckPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    status: str
    message: str = ""
    executed_at: str | None = None
    known_command: bool = False


class CommandAckEnvelope(_EnvelopeBase):
    type: Literal["command_ack"]
    payload: CommandAckPayload


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    severity: str | None = None
    message: str | None = None
    id: int | None = None
    acknowledged_at: str | None = None


class EventEnvelope(_EnvelopeBase):
    type: Literal["event"]
    payload: EventPayload


class LogEnvelope(_EnvelopeBase):
    type: Literal["log"]
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    topic: str
    error: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(_EnvelopeBase):
    type: Literal["error"]
    payload: ErrorPayload


class AiAnalyzingPayload(BaseModel):
    trigger: str


class AiAnalyzingEnvelope(_EnvelopeBase):
    type: Literal["ai_analyzing"]
    payload: AiAnalyzingPayload


class AiResultEnvelope(_EnvelopeBase):
    type: Literal["ai_result"]
    payload: AiDecisionOut


class AutopilotEnvelope(_EnvelopeBase):
    type: Literal["autopilot"]
    payload: AutopilotState


WsMessage = Annotated[
    TelemetryEnvelope
    | StatusEnvelope
    | ImageEnvelope
    | PoseEnvelope
    | CommandEnvelope
    | NotificationEnvelope
    | CommandAckEnvelope
    | EventEnvelope
    | LogEnvelope
    | ErrorEnvelope
    | AiAnalyzingEnvelope
    | AiResultEnvelope
    | AutopilotEnvelope,
    Field(discriminator="type"),
]
