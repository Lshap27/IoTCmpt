from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas import AiDecision, CommandMessage

LOGGER = logging.getLogger(__name__)

# 固件实际可执行的命令集合（display.message 会被固件 ack rejected，不向模型宣传）。
EXECUTABLE_COMMANDS: list[str] = ["none", "window.open", "window.close", "alarm.on", "alarm.off"]
RISK_LEVELS: set[str] = {"low", "medium", "high"}

DECISION_JSON_SCHEMA: dict[str, Any] = {
    "name": "device_command_decision",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": EXECUTABLE_COMMANDS},
            "parameter": {"type": "object", "additionalProperties": True},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "risk_level": {"type": "string", "enum": sorted(RISK_LEVELS)},
            "reason": {"type": "string"},
        },
        "required": ["type", "confidence", "risk_level", "reason"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = (
    "你是 ESP32-S3 室内环境设备的云端决策助手。设备位于室内，配有温湿度、TVOC/甲醛/eCO2、"
    "光照传感器，以及舵机窗户和蜂鸣器报警。你会收到设备最新状态快照（含 fusion 空气质量评估）、"
    "近期遥测趋势，可能还有一张刚拍摄的室内照片。\n"
    f"可执行的命令类型只有：{json.dumps(EXECUTABLE_COMMANDS)}。\n"
    "决策原则：空气质量 alert 且窗户未开时倾向 window.open；环境恢复正常且窗户为自动打开状态时"
    "可以 window.close；出现明显危险（浓烟、明火、有人晕倒等图像异常，或污染物极高）时 alarm.on；"
    "危险解除时 alarm.off；无需动作时返回 none。若照片与遥测矛盾，以更保守（更安全）的动作为准。\n"
    "只返回一个 JSON 对象，不要包含任何其他文字，字段为："
    '{"type": string, "parameter": object, "confidence": number(0-1), '
    '"risk_level": "low"|"medium"|"high", "reason": string}。reason 用简体中文，简明说明依据。'
)


def extract_json_object(content: Any) -> dict[str, Any]:
    """尽力从模型返回内容中提取 JSON 对象（容忍代码栅栏、分段 content、前后缀文本）。"""
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    text = str(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM content is not a JSON object")
    return parsed


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def analyze(self, device_state: dict[str, Any], *, image_path: Path | None = None) -> AiDecision:
        if self.settings.llm_endpoint == "mock":
            return self._mock_decision(device_state)

        if not self.settings.llm_endpoint or not self.settings.llm_api_key:
            return self._none_decision("LLM 未配置")

        try:
            parsed = await self._call_openai_compatible(device_state, image_path=image_path)
        except Exception as exc:
            LOGGER.warning("LLM call failed: %s", exc)
            return self._none_decision(f"LLM 调用失败: {exc}")

        return self._decision_from_payload(parsed)

    def _none_decision(self, reason: str, *, risk_level: str = "unknown") -> AiDecision:
        return AiDecision(
            command=CommandMessage(type="none", source="llm", reason=reason),
            risk_level=risk_level,
            summary=reason,
            model=self.settings.llm_model,
        )

    def _decision_from_payload(self, parsed: dict[str, Any]) -> AiDecision:
        raw_type = str(parsed.get("type") or parsed.get("command") or "none")
        if raw_type not in EXECUTABLE_COMMANDS:
            return self._none_decision(f"LLM 返回了不可执行的指令: {raw_type}")

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.0

        parameter = parsed.get("parameter") or {}
        if not isinstance(parameter, dict):
            parameter = {"value": str(parameter)}

        risk_level = str(parsed.get("risk_level") or "").lower()
        if risk_level not in RISK_LEVELS:
            risk_level = "unknown"

        reason = str(parsed.get("reason") or parsed.get("summary") or "")
        return AiDecision(
            command=CommandMessage(
                type=raw_type,
                parameter=parameter,
                source="llm",
                confidence=confidence,
                reason=reason,
            ),
            risk_level=risk_level,
            summary=str(parsed.get("summary") or reason),
            model=self.settings.llm_model,
        )

    def _mock_decision(self, device_state: dict[str, Any]) -> AiDecision:
        """确定性的离线决策，保证无 API key 时也能演示完整闭环。"""
        telemetry = device_state.get("telemetry") or {}
        fusion = telemetry.get("fusion") or {}
        state = telemetry.get("state") or {}
        air_quality = fusion.get("air_quality")

        if air_quality == "alert" and not state.get("window_open"):
            command_type, confidence, risk, reason = (
                "window.open",
                0.9,
                "medium",
                "空气质量达到 alert，窗户未开，建议立即开窗通风",
            )
        elif air_quality == "alert" and fusion.get("alarm_enabled"):
            command_type, confidence, risk, reason = (
                "alarm.on",
                0.85,
                "high",
                "空气质量持续 alert 且已开窗，触发报警提醒",
            )
        elif fusion.get("alarm_enabled"):
            command_type, confidence, risk, reason = (
                "alarm.on",
                0.85,
                "medium",
                "融合评估要求报警",
            )
        elif air_quality == "good" and state.get("alarm_on"):
            command_type, confidence, risk, reason = (
                "alarm.off",
                0.8,
                "low",
                "环境已恢复正常，关闭报警",
            )
        else:
            command_type, confidence, risk, reason = ("none", 0.95, "low", "环境正常，无需动作")

        return AiDecision(
            command=CommandMessage(
                type=command_type,
                source="llm",
                confidence=confidence,
                reason=reason,
            ),
            risk_level=risk,
            summary=reason,
            model="mock",
        )

    def _build_messages(self, device_state: dict[str, Any], image_bytes: bytes | None) -> list[dict[str, Any]]:
        user_text = "当前设备状态快照与近期遥测趋势如下，请给出决策 JSON：\n" + json.dumps(
            device_state, ensure_ascii=False, default=str
        )
        if image_bytes is None:
            user_content: Any = user_text
        else:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            user_content = [
                {"type": "text", "text": user_text + "\n随附设备刚上传的室内照片，请结合画面判断。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            ]
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _response_format(self) -> dict[str, Any] | None:
        if self.settings.llm_response_format == "json_schema":
            return {"type": "json_schema", "json_schema": DECISION_JSON_SCHEMA}
        if self.settings.llm_response_format == "json_object":
            return {"type": "json_object"}
        return None

    def _read_image(self, image_path: Path | None) -> bytes | None:
        if image_path is None or not self.settings.llm_vision_enabled:
            return None
        try:
            return image_path.read_bytes()
        except OSError as exc:
            LOGGER.warning("failed to read image %s, falling back to text-only: %s", image_path, exc)
            return None

    async def _call_openai_compatible(
        self, device_state: dict[str, Any], *, image_path: Path | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self._build_messages(device_state, self._read_image(image_path)),
            "temperature": 0.1,
        }
        response_format = self._response_format()
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            response = await client.post(self.settings.llm_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "type" in data or "command" in data:
            return data
        content = data["choices"][0]["message"]["content"]
        return extract_json_object(content)
