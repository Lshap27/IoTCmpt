from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas import CloudCommandResponse, CloudExchangeRequest
from app.services.command_service import validate_cloud_command


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def exchange(self, request: CloudExchangeRequest) -> CloudCommandResponse:
        if not self.settings.llm_endpoint or not self.settings.llm_api_key:
            return CloudCommandResponse(command="none", confidence=0.0, reason="LLM 未配置")

        try:
            parsed = self._call_openai_compatible(request)
        except Exception as exc:
            return CloudCommandResponse(command="none", confidence=0.0, reason=f"LLM 调用失败: {exc}")

        raw_command = str(parsed.get("command", "none"))
        command = validate_cloud_command(raw_command, request.allowed_commands)
        if command == "none" and raw_command != "none":
            return CloudCommandResponse(command="none", confidence=0.0, reason=f"LLM 返回了不允许的指令: {raw_command}")

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.0
        return CloudCommandResponse(
            command=command,
            confidence=confidence,
            parameter=str(parsed.get("parameter") or ""),
            reason=str(parsed.get("reason") or ""),
        )

    def _call_openai_compatible(self, request: CloudExchangeRequest) -> dict[str, Any]:
        prompt = (
            "You are controlling a dorm IoT device. Return only JSON with keys "
            "command, confidence, parameter, reason. The command must be one of "
            f"{request.allowed_commands or ['none']}."
        )
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "requested_model": request.model,
                            "device_state": request.device_state,
                            "allowed_commands": request.allowed_commands,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            response = client.post(self.settings.llm_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "command" in data:
            return data
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)
