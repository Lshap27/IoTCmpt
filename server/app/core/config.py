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

    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_client_id: str = "aiot-gateway"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_reconnect_seconds: float = 3.0

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_model: str = "demo-model"
    llm_timeout_seconds: float = 12.0
    llm_vision_enabled: bool = True
    llm_image_max_age_seconds: float = 600.0
    llm_response_format: str = "json_object"

    autopilot_enabled: bool = True
    autopilot_cooldown_seconds: float = 120.0
    autopilot_min_confidence: float = 0.6
    autopilot_trigger_levels: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["alert"])

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

    @field_validator("base_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
