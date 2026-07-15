from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIOT_", env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://aiot:aiot@127.0.0.1:5432/aiot"
    auto_create_tables: bool = True

    base_url: str = "http://127.0.0.1:8000"
    uploads_dir: Path = Path("uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    max_images_per_device: int = 100

    pose_enabled: bool = False
    pose_model_path: Path = Path("models/pose_landmarker_full.task")
    pose_detection_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    pose_presence_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    pose_tracking_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    pose_landmark_visibility: float = Field(default=0.5, ge=0.0, le=1.0)
    pose_forward_lean_degrees: float = Field(default=20.0, ge=0.0, le=90.0)
    pose_hunch_ratio: float = Field(default=0.25, ge=0.0, le=2.0)
    pose_head_down_degrees: float = Field(default=25.0, ge=-90.0, le=90.0)
    person_detection_enabled: bool = True
    person_detection_model_path: Path = Path("models/efficientdet_lite0_int8.tflite")
    person_detection_confidence: float = Field(default=0.35, ge=0.0, le=1.0)

    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_client_id: str = "aiot-gateway"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_reconnect_seconds: float = 3.0
    command_ack_timeout_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)

    mcp_enabled: bool = False
    mcp_internal_token: str = ""
    mcp_read_token: str = ""
    mcp_control_token: str = ""
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "aiot.internal", "testserver"]
    )
    mcp_rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)

    ai_worker_enabled: bool = True
    ai_worker_poll_seconds: float = Field(default=0.5, ge=0.1, le=30.0)
    ai_worker_lease_seconds: int = Field(default=90, ge=30, le=900)
    ai_worker_heartbeat_seconds: int = Field(default=15, ge=5, le=120)
    ai_worker_max_attempts: int = Field(default=3, ge=1, le=10)
    ai_tool_max_rounds: int = Field(default=4, ge=1, le=10)
    ai_tool_max_calls: int = Field(default=8, ge=1, le=32)
    patrol_scheduler_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    automation_scheduler_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    gateway_internal_url: str = "http://127.0.0.1:8000"
    outbox_lease_seconds: int = Field(default=30, ge=10, le=300)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_endpoint: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = 60.0
    llm_image_max_age_seconds: float = 600.0
    llm_response_format: str = "json_object"
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: str = "high"

    vision_image_max_age_seconds: float = Field(default=15.0, ge=1.0, le=120.0)

    @field_validator(
        "cors_origins",
        "mcp_allowed_origins",
        "mcp_allowed_hosts",
        mode="before",
    )
    @classmethod
    def split_comma_list(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("llm_response_format")
    @classmethod
    def check_response_format(cls, value: str) -> str:
        allowed = {"json_object", "json_schema", "none"}
        if value not in allowed:
            raise ValueError(f"llm_response_format must be one of {sorted(allowed)}")
        return value

    @field_validator("llm_reasoning_effort")
    @classmethod
    def check_reasoning_effort(cls, value: str) -> str:
        allowed = {"high", "max"}
        if value not in allowed:
            raise ValueError(f"llm_reasoning_effort must be one of {sorted(allowed)}")
        return value

    @field_validator("base_url", "gateway_internal_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_mcp_tokens(self) -> Settings:
        if self.mcp_enabled:
            if not self.mcp_read_token or not self.mcp_control_token:
                raise ValueError("external MCP requires both read and control tokens")
            if self.mcp_read_token == self.mcp_control_token:
                raise ValueError("MCP read and control tokens must be different")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
