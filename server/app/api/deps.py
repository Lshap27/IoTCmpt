from __future__ import annotations

from app.core.config import get_settings
from app.services.llm import LLMService


def get_llm_service() -> LLMService:
    return LLMService(get_settings())

