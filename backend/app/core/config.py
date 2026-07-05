from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "mysql+pymysql://iot_backend:iot_backend@127.0.0.1:3306/iot_backend"
    auto_create_tables: bool = False

    images_dir: Path = Path("data/images")
    base_url: str = "http://127.0.0.1:8000"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_images: int = 100
    max_image_age_days: int = 14

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:8000"])
    device_token: str = ""

    pose_model_path: Path = Path("pose_landmarker_lite.task")

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


settings = get_settings()
