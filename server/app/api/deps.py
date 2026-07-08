from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.services.autopilot import AutoPilot
from app.services.llm import LLMService
from app.services.mqtt import MqttGateway


def get_llm_service() -> LLMService:
    return LLMService(get_settings())


def get_mqtt_gateway(request: Request) -> MqttGateway | None:
    return getattr(request.app.state, "mqtt_service", None)


def get_autopilot_or_none(request: Request) -> AutoPilot | None:
    return getattr(request.app.state, "autopilot", None)


def get_autopilot(request: Request) -> AutoPilot:
    autopilot = getattr(request.app.state, "autopilot", None)
    if autopilot is None:
        raise HTTPException(status_code=503, detail="Autopilot is not available")
    return autopilot
