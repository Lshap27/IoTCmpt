from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
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

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_endpoint: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = 12.0
    llm_image_max_age_seconds: float = 600.0
    llm_response_format: str = "json_object"
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: str = "high"

    autopilot_enabled: bool = True
    autopilot_cooldown_seconds: float = 120.0
    autopilot_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    autopilot_trigger_levels: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["alert"],
        description="Deprecated: 空气质量与烟雾自动规则已移至固件；保留此配置仅用于兼容旧部署。",
    )
    vision_interval_enabled: bool = False
    vision_interval_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)
    vision_image_max_age_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    sedentary_threshold_seconds: float = Field(default=7200.0, ge=5.0, le=28800.0)
    smoke_silence_seconds: int = Field(default=60, ge=10, le=600)

    @field_validator("cors_origins", "autopilot_trigger_levels", mode="before")
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

    @field_validator("autopilot_trigger_levels")
    @classmethod
    def check_autopilot_trigger_levels(cls, value: list[str]) -> list[str]:
        allowed = {"good", "watch", "alert"}
        normalized = list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))
        if not normalized or any(item not in allowed for item in normalized):
            raise ValueError("autopilot_trigger_levels must contain one or more of: good, watch, alert")
        return normalized

    @field_validator("base_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
