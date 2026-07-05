from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SensorUpload(BaseModel):
    model_config = ConfigDict(extra="allow")

    temperature_in: Optional[float] = None
    humidity_in: Optional[float] = None
    temperature_out: Optional[float] = None
    humidity_out: Optional[float] = None
    co2: Optional[float] = None
    tvoc: Optional[float] = None
    hcho: Optional[float] = None
    light: Optional[int] = None
    led_status: Optional[str] = None
    window_status: Optional[str] = None
    dehumidifier_state: Optional[str] = None
    air_quality: Optional[str] = None
    recommend_open_window: Optional[bool] = None
    alarm_enabled: Optional[bool] = None
    reason: Optional[str] = None


class CommandCreate(BaseModel):
    command: Optional[str] = None
    device: Optional[str] = None
    value: Optional[str] = None
    parameter: Optional[str] = None
    source: str = "frontend"
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class CommandAckResponse(BaseModel):
    status: str
    message: str


class CloudExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = None
    device_state: dict[str, Any] = Field(default_factory=dict)
    allowed_commands: list[str] = Field(default_factory=list)


class CloudCommandResponse(BaseModel):
    command: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    parameter: str = ""
    reason: str = ""


class StoredImage(BaseModel):
    filename: str
    path: str
    url: str


HumanPresence = Literal["yes", "no", "unknown"]
