from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas import CommandMessage
from app.services.commands import ALLOWED_COMMANDS, validate_command_type


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(self, device_state: dict[str, Any]) -> CommandMessage:
        if not self.settings.llm_endpoint or not self.settings.llm_api_key:
            return CommandMessage(type="none", source="llm", reason="LLM 未配置")

        try:
            parsed = self._call_openai_compatible(device_state)
        except Exception as exc:
            return CommandMessage(type="none", source="llm", reason=f"LLM 调用失败: {exc}")

        raw_type = str(parsed.get("type") or parsed.get("command") or "none")
        command_type = validate_command_type(raw_type)
        if command_type == "none" and raw_type != "none":
            return CommandMessage(type="none", source="llm", reason=f"LLM 返回了不允许的指令: {raw_type}")

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.0

        parameter = parsed.get("parameter") or {}
        if not isinstance(parameter, dict):
            parameter = {"value": str(parameter)}

        return CommandMessage(
            type=command_type,
            parameter=parameter,
            source="llm",
            confidence=confidence,
            reason=str(parsed.get("reason") or parsed.get("summary") or ""),
        )

    def _call_openai_compatible(self, device_state: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "You control an ESP32-S3 AIoT device. Return only JSON with keys "
            "type, parameter, confidence, reason. The type must be one of "
            f"{sorted(ALLOWED_COMMANDS)}."
        )
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(device_state, ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            response = client.post(self.settings.llm_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "type" in data or "command" in data:
            return data
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)

