from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


CommandType = Literal[
    "none",
    "window.open",
    "window.close",
    "alarm.on",
    "alarm.off",
    "display.message",
]
CommandSource = Literal["frontend", "llm", "rule"]


class SensorPayload(BaseModel):
    temperature_c: Optional[float] = None
    humidity_percent: Optional[float] = None
    tvoc_ppb: Optional[float] = None
    hcho_ug_m3: Optional[float] = None
    eco2_ppm: Optional[float] = None
    light_is_dark: Optional[bool] = None


class DeviceStatePayload(BaseModel):
    window_open: Optional[bool] = None
    alarm_on: Optional[bool] = None
    manual_override: Optional[bool] = None


class FusionPayload(BaseModel):
    air_quality: Literal["good", "watch", "alert", "unknown"] = "unknown"
    recommend_open_window: bool = False
    alarm_enabled: bool = False
    reason: str = ""


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    device_id: str
    sampled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensors: SensorPayload = Field(default_factory=SensorPayload)
    state: DeviceStatePayload = Field(default_factory=DeviceStatePayload)
    fusion: FusionPayload = Field(default_factory=FusionPayload)


class CommandIn(BaseModel):
    type: CommandType
    parameter: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class CommandMessage(BaseModel):
    command_id: str = Field(default_factory=lambda: f"cmd-{uuid4().hex[:16]}")
    type: CommandType
    parameter: dict[str, Any] = Field(default_factory=dict)
    source: CommandSource = "frontend"
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommandAckIn(BaseModel):
    device_id: str
    command_id: str
    status: Literal["executed", "rejected", "failed"]
    message: str = ""
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AiAnalyzeResponse(CommandMessage):
    pass


RiskLevel = Literal["low", "medium", "high", "unknown"]


class AiDecision(BaseModel):
    command: CommandMessage
    risk_level: RiskLevel = "unknown"
    summary: str = ""
    model: str = ""


class AutopilotIn(BaseModel):
    enabled: bool


class ImageAssetOut(BaseModel):
    id: int
    device_id: str
    url: str
    created_at: datetime


class WebSocketEnvelope(BaseModel):
    type: str
    device_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)

