from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, cast

import httpx

from app.core.config import Settings
from app.schemas import AiDecision, CommandMessage, CommandType, RiskLevel

LOGGER = logging.getLogger(__name__)

# 固件实际可执行的命令集合（display.message 会被固件 ack rejected，不向模型宣传）。
EXECUTABLE_COMMANDS: list[str] = [
    "none",
    "window.open",
    "window.close",
    "led.on",
    "led.off",
]
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
            "speech": {"type": "string", "maxLength": 60},
            "scene_summary": {"type": "string"},
        },
        "required": ["type", "confidence", "risk_level", "reason", "speech", "scene_summary"],
        "additionalProperties": False,
    },
}

REPORT_SYSTEM_PROMPT = (
    "你是室内环境健康分析助手。请仅依据提供的聚合遥测、事件和数据完整性生成报告，不补造缺失数据。"
    "只能使用输入中的 operational_thresholds 判断超标，不得虚构法规、医学结论或未提供的安全上限。"
    "输出一个 JSON 对象，字段必须为 risk_level(low/medium/high)、risk_score(0-100)、headline、summary、"
    "anomalies(string[])、recommendations(string[])、next_checks(string[])。建议应具体、可执行并按优先级排序；"
    "若数据不足，必须在 summary 和 next_checks 中明确说明。"
)

SYSTEM_PROMPT = (
    "你是 ESP32-S3 室内环境设备的云端决策助手。设备位于室内，配有温湿度、TVOC/甲醛/eCO2、"
    "光照和烟雾传感器，以及舵机窗户、LED 和蜂鸣器报警。你会收到设备最新状态快照（含 fusion 空气质量评估）、"
    "近期遥测趋势，可能还有一张刚拍摄的室内照片。\n"
    f"可执行的命令类型只有：{json.dumps(EXECUTABLE_COMMANDS)}。\n"
    "决策原则：必须先检查 state.window_open、air_trend 和 actions_already_taken。空气质量变差且窗户未开时才可"
    "window.open；窗户已经打开时禁止再次建议开窗，应建议检查污染源、通风路径或远离风险区域。"
    "air_trend=worsening 时禁止 window.close。光照不足且有人时可以 led.on，无人或明亮时可以 led.off；"
    "自动决策不得控制蜂鸣器，无需动作时返回 none。"
    "烟雾报警由设备本地独立执行，云端不得用 window.open 替代报警。若照片与遥测矛盾，以更保守（更安全）的动作为准。\n"
    "只返回一个 JSON 对象，不要包含任何其他文字，字段为："
    '{"type": string, "parameter": object, "confidence": number(0-1), '
    '"risk_level": "low"|"medium"|"high", "reason": string, "speech": string, "scene_summary": string}。'
    "reason 用简体中文说明依据；speech 仅在输入要求语音时填写一至两句、最多六十字，否则为空字符串。"
)


class VisionUnsupportedError(RuntimeError):
    pass


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
        except VisionUnsupportedError:
            raise
        except Exception as exc:
            LOGGER.warning("LLM call failed: %s", exc)
            return self._none_decision(f"LLM 调用失败: {exc}")

        return self._decision_from_payload(parsed)

    async def generate_report(self, context: dict[str, Any]) -> dict[str, Any]:
        if self.settings.llm_endpoint == "mock":
            return self._mock_report(context)
        if not self.settings.llm_endpoint or not self.settings.llm_api_key:
            raise RuntimeError("LLM 未配置，无法生成 AI 报告")
        messages = [
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "请根据以下数据生成 JSON 健康报告：\n"
                + json.dumps(context, ensure_ascii=False, default=str),
            },
        ]
        return await self._call_json(messages)

    def _none_decision(self, reason: str, *, risk_level: RiskLevel = "unknown") -> AiDecision:
        return AiDecision(
            command=CommandMessage(type="none", source="llm", reason=reason),
            risk_level=risk_level,
            summary=reason,
            model=self.settings.llm_model,
            speech="",
            scene_summary="",
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
                type=cast(CommandType, raw_type),
                parameter=parameter,
                source="llm",
                confidence=confidence,
                reason=reason,
            ),
            risk_level=cast(RiskLevel, risk_level),
            summary=str(parsed.get("summary") or reason),
            model=self.settings.llm_model,
            speech=str(parsed.get("speech") or "")[:60],
            scene_summary=str(parsed.get("scene_summary") or parsed.get("summary") or reason),
        )

    def _mock_decision(self, device_state: dict[str, Any]) -> AiDecision:
        """确定性的离线决策，保证无 API key 时也能演示完整闭环。"""
        telemetry = device_state.get("telemetry") or {}
        fusion = telemetry.get("fusion") or {}
        state = telemetry.get("state") or {}
        sensors = telemetry.get("sensors") or {}
        pose = device_state.get("pose") or {}
        air_quality = fusion.get("air_quality")

        if sensors.get("smoke_detected"):
            command_type, confidence, risk, reason = (
                ("none", 0.99, "high", "MQ-2 烟雾报警已由设备本地持续执行")
                if state.get("alarm_on")
                else ("alarm.on", 0.99, "high", "MQ-2 检测到烟雾，保持本地紧急报警")
            )
        elif air_quality == "alert" and not state.get("window_open"):
            command_type, confidence, risk, reason = (
                "window.open",
                0.9,
                "medium",
                "空气质量达到 alert，窗户未开，建议立即开窗通风",
            )
        elif air_quality == "alert" and state.get("window_open"):
            command_type, confidence, risk, reason = (
                "none",
                0.9,
                "high" if device_state.get("air_trend") == "worsening" else "medium",
                "窗户已经打开，空气仍未改善，应检查室内污染源和通风路径",
            )
        elif pose.get("human_present") and sensors.get("light_is_dark") and state.get("led_on") is False:
            command_type, confidence, risk, reason = ("led.on", 0.8, "low", "室内光照偏暗，开启照明")
        elif state.get("led_on") and (not pose.get("human_present") or not sensors.get("light_is_dark")):
            command_type, confidence, risk, reason = ("led.off", 0.9, "low", "当前无人或环境明亮，关闭照明")
        else:
            command_type, confidence, risk, reason = ("none", 0.95, "low", "环境正常，无需动作")

        intent = str(device_state.get("analysis_intent") or "")
        speech = ""
        if intent == "smoke":
            speech = "检测到烟雾，请立即远离并检查现场安全。"
        elif intent == "air_change":
            speech = "空气质量正在变差，请检查污染源并保持有效通风。"
        elif intent == "sedentary":
            speech = "您已久坐较长时间，请起身活动并放松肩颈。"
        return AiDecision(
            command=CommandMessage(
                type=cast(CommandType, command_type),
                source="llm",
                confidence=confidence,
                reason=reason,
            ),
            risk_level=cast(RiskLevel, risk),
            summary=reason,
            model="mock",
            speech=speech,
            scene_summary=reason,
        )

    def _mock_report(self, context: dict[str, Any]) -> dict[str, Any]:
        metrics = context.get("metrics") or {}
        coverage = context.get("coverage") or {}
        anomalies: list[str] = []
        recommendations: list[str] = []
        score = 10
        if metrics.get("alert_bucket_count", 0):
            anomalies.append(f"空气质量告警时段共 {metrics['alert_bucket_count']} 个")
            recommendations.append("优先排查 TVOC、甲醛或 eCO₂ 的持续污染源，并加强通风")
            score = max(score, 65)
        if (metrics.get("eco2_max_ppm") or 0) > 1000:
            anomalies.append(f"eCO₂ 峰值达到 {metrics['eco2_max_ppm']:.0f} ppm")
            recommendations.append("在人员密集或睡眠时段增加定时通风")
            score = max(score, 55)
        if metrics.get("smoke_event_count", 0):
            anomalies.append(f"记录到 {metrics['smoke_event_count']} 次烟雾事件")
            recommendations.insert(0, "立即核对烟雾告警台账并检查现场安全")
            score = max(score, 90)
        completeness = coverage.get("completeness_percent", 0)
        next_checks = ["继续观察下一时段趋势，并确认建议执行后的指标变化"]
        if completeness < 80:
            next_checks.insert(0, "先检查设备在线状态和采样间隔，补足数据后再比较趋势")
        risk = "high" if score >= 80 else "medium" if score >= 40 else "low"
        return {
            "risk_level": risk,
            "risk_score": score,
            "headline": "环境需要关注" if risk != "low" else "环境总体稳定",
            "summary": f"本时段共分析 {coverage.get('sample_count', 0)} 条采样，数据完整度约 {completeness:.1f}%。",
            "anomalies": anomalies or ["未发现明显异常"],
            "recommendations": recommendations or ["维持当前通风和巡检节奏"],
            "next_checks": next_checks,
        }

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
        if image_path is None:
            return None
        try:
            return image_path.read_bytes()
        except OSError as exc:
            LOGGER.warning("failed to read image %s, falling back to text-only: %s", image_path, exc)
            return None

    async def _call_openai_compatible(
        self, device_state: dict[str, Any], *, image_path: Path | None = None
    ) -> dict[str, Any]:
        messages = self._build_messages(device_state, self._read_image(image_path))
        return await self._call_json(messages)

    async def _call_json(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.settings.llm_model, "messages": messages}
        if self.settings.llm_thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        else:
            payload["temperature"] = 0.1
        response_format = self._response_format()
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            response = await client.post(self.settings.llm_endpoint, json=payload, headers=headers)
            if response.status_code in {400, 415, 422} and any(
                marker in response.text.lower() for marker in ("image", "vision", "multimodal", "image_url")
            ):
                raise VisionUnsupportedError("当前模型不支持图片分析")
            response.raise_for_status()
            data = response.json()

        if "type" in data or "command" in data or "headline" in data:
            return data
        content = data["choices"][0]["message"]["content"]
        return extract_json_object(content)
