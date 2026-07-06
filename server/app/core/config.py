from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_model: str = "demo-model"
    llm_timeout_seconds: float = 12.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("base_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()

