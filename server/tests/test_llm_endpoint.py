from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from app.core.config import Settings
from app.services.llm import LLMService, resolve_chat_completions_url


def test_deepseek_base_url_gets_chat_completions_suffix():
    assert resolve_chat_completions_url("https://api.deepseek.com") == ("https://api.deepseek.com/chat/completions")


def test_versioned_base_url_and_trailing_slash_are_normalized():
    assert resolve_chat_completions_url("https://example.com/v1/") == ("https://example.com/v1/chat/completions")


def test_legacy_full_endpoint_is_not_duplicated():
    endpoint = "https://example.com/openai/v1/chat/completions?api-version=2026-01-01"
    assert resolve_chat_completions_url(endpoint) == endpoint


def test_default_online_model_is_doubao_flash_via_volcengine_gateway():
    settings = Settings(_env_file=None)

    assert settings.llm_endpoint == "https://ai-gateway.vei.volces.com/v1"
    assert settings.llm_model == "Doubao-Seed-1.6-flash"


class _FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "model": "doubao-seed-1-6-flash-250828",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-demo",
                                "type": "function",
                                "function": {"name": "automation_plan_create_draft", "arguments": "{}"},
                            }
                        ],
                    }
                }
            ],
        }


class _FakeAsyncClient:
    captured: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_kwargs: Any):
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.captured = {"url": url, "json": json, "headers": headers}
        type(self).captured = self.captured
        return _FakeResponse()


def test_volcengine_forced_tool_call_uses_standard_openai_payload(monkeypatch):
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _FakeAsyncClient)
    settings = Settings(
        _env_file=None,
        llm_endpoint="https://ai-gateway.vei.volces.com/v1",
        llm_api_key="test-key",
        llm_model="Doubao-Seed-1.6-flash",
        llm_thinking_enabled=True,
    )
    message = asyncio.run(
        LLMService(settings).complete_with_tools(
            [{"role": "user", "content": "demo"}],
            [{"type": "function", "function": {"name": "automation_plan_create_draft", "parameters": {}}}],
            required_tool="automation_plan_create_draft",
        )
    )

    payload = _FakeAsyncClient.captured["json"]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "automation_plan_create_draft"},
    }
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload
    assert message["_response_model"] == "doubao-seed-1-6-flash-250828"


def test_deepseek_forced_tool_call_explicitly_disables_thinking(monkeypatch):
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _FakeAsyncClient)
    settings = Settings(
        _env_file=None,
        llm_endpoint="https://api.deepseek.com",
        llm_api_key="test-key",
        llm_model="deepseek-v4-flash",
        llm_thinking_enabled=True,
    )
    asyncio.run(
        LLMService(settings).complete_with_tools(
            [{"role": "user", "content": "demo"}],
            [{"type": "function", "function": {"name": "automation_plan_create_draft", "parameters": {}}}],
            required_tool="automation_plan_create_draft",
        )
    )

    payload = _FakeAsyncClient.captured["json"]
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
