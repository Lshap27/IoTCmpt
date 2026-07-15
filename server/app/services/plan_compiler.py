from __future__ import annotations

import re
from typing import Any

from app.domain.automation_plans import validate_plan_spec


def _seconds(value: float, unit: str) -> int:
    if unit in {"秒", "second", "seconds"}:
        return round(value)
    return round(value * (3600 if unit in {"小时", "hour", "hours"} else 60))


def _time_value(raw: str) -> float:
    return 0.5 if raw == "半" else float(raw)


def _reminder_text(goal: str) -> str:
    quoted = re.search(r"提醒我\s*[：:,，]?\s*[“\"](.+?)[”\"]", goal)
    if quoted:
        return quoted.group(1).strip()
    plain = re.search(r"提醒我\s*[：:,，]?\s*(.+?)(?:[。；;]|$)", goal)
    if plain:
        return plain.group(1).strip(' \t，,。；;"“”')
    return ""


def compile_mock_plan(goal: str, *, timezone: str = "Asia/Shanghai") -> tuple[dict[str, Any], str]:
    """Compile the supported Chinese demo grammar without bypassing plan validation."""
    duration_seconds: int | None = None
    duration = re.search(
        r"(?:持续|学习|计划(?:进行)?)\s*(\d+|半)\s*(秒|分钟|小时|seconds?|minutes?|hours?)",
        goal,
        re.IGNORECASE,
    )
    if duration:
        duration_seconds = _seconds(_time_value(duration.group(1)), duration.group(2).lower())

    clarifications: list[str] = []
    if duration_seconds is not None and not 60 <= duration_seconds <= 86400:
        clarifications.append("计划持续时间必须在 1 分钟到 24 小时之间")
        duration_seconds = max(60, min(duration_seconds, 86400))

    rules: list[dict[str, Any]] = []
    dark_present = any(
        keyword in goal
        for keyword in (
            "光线暗且有人",
            "光线暗并且有人",
            "光线暗并且检测到有人",
            "暗光且有人",
            "暗光有人",
        )
    )
    if any(keyword in goal for keyword in ("光线暗", "光照暗", "太暗", "暗就开灯", "暗光")):
        items: list[dict[str, Any]] = [{"fact": "light_is_dark", "op": "eq", "value": True}]
        if dark_present:
            items.append({"fact": "human_present", "op": "eq", "value": True})
        rules.append(
            {
                "id": "dark-lighting",
                "description": "光线持续偏暗且检测到有人时开启照明" if dark_present else "光线持续偏暗时开启照明",
                "trigger": {
                    "type": "condition",
                    "mode": "all",
                    "items": items,
                    "stability_samples": 2,
                },
                "action": {"command": "led.on", "parameter": {}},
                "cooldown_seconds": 30,
            }
        )
    bright_absent = any(
        keyword in goal
        for keyword in (
            "光线明亮且无人",
            "光线明亮并且无人",
            "光线明亮并且确认无人",
            "明亮且无人",
            "明亮无人",
        )
    )
    if bright_absent and "关灯" in goal:
        rules.append(
            {
                "id": "bright-empty-lighting",
                "description": "光线持续明亮且确认无人时关闭照明",
                "trigger": {
                    "type": "condition",
                    "mode": "all",
                    "items": [
                        {"fact": "light_is_dark", "op": "eq", "value": False},
                        {"fact": "human_present", "op": "eq", "value": False},
                    ],
                    "stability_samples": 2,
                },
                "action": {"command": "led.off", "parameter": {}},
                "cooldown_seconds": 30,
            }
        )
    if any(keyword in goal for keyword in ("空气不好", "空气差", "空气质量差", "空气异常")):
        rules.append(
            {
                "id": "air-ventilation",
                "description": "空气质量达到告警级别时开窗通风",
                "trigger": {
                    "type": "condition",
                    "mode": "all",
                    "items": [{"fact": "air_quality", "op": "eq", "value": "alert"}],
                    "stability_samples": 1,
                },
                "action": {"command": "window.open", "parameter": {}},
                "cooldown_seconds": 300,
            }
        )
    reminder_text = _reminder_text(goal)
    delay = re.search(r"(\d+|半)\s*(秒|分钟|小时)\s*后", goal)
    if delay and "提醒" in goal:
        delay_seconds = _seconds(_time_value(delay.group(1)), delay.group(2))
        if 15 <= delay_seconds <= 86400:
            rules.append(
                {
                    "id": "drink-water-reminder" if "喝水" in reminder_text else "one-time-reminder",
                    "description": f"激活后 {delay_seconds} 秒提醒一次",
                    "trigger": {"type": "delay", "after_seconds": delay_seconds},
                    "action": {
                        "command": "voice.speak",
                        "parameter": {},
                        "text": reminder_text or "提醒时间到了。",
                    },
                    "cooldown_seconds": 0,
                }
            )
        else:
            clarifications.append("一次性提醒延迟必须在 15 秒到 24 小时之间")

    interval = re.search(r"每\s*(\d+|半)\s*(秒|分钟|小时)", goal)
    if interval:
        interval_seconds = _seconds(_time_value(interval.group(1)), interval.group(2))
        if 15 <= interval_seconds <= 86400:
            rules.append(
                {
                    "id": "activity-reminder",
                    "description": f"每 {interval_seconds} 秒提醒一次",
                    "trigger": {"type": "interval", "every_seconds": interval_seconds},
                    "action": {
                        "command": "voice.speak",
                        "parameter": {},
                        "text": reminder_text or "请起身活动一下，放松肩颈。",
                    },
                    "cooldown_seconds": 0,
                }
            )
        else:
            clarifications.append("提醒间隔必须在 15 秒到 24 小时之间")

    timed_rules = [rule for rule in rules if rule["trigger"]["type"] in {"delay", "interval"}]
    if duration_seconds is None:
        delays = [rule["trigger"]["after_seconds"] for rule in timed_rules if rule["trigger"]["type"] == "delay"]
        if delays:
            duration_seconds = max(60, max(delays) + 30)
        elif timed_rules:
            duration_seconds = 60
        else:
            duration_seconds = 3600
            clarifications.append("请确认计划持续时间")
    if not rules:
        clarifications.append("请说明需要执行的光照、通风或提醒动作")

    spec = {
        "schema_version": "1.0",
        "title": "喝水提醒" if "喝水" in reminder_text else "AI 学习自动化计划" if "学习" in goal else "AI 自动化计划",
        "duration_seconds": duration_seconds,
        "timezone": timezone,
        "manual_override_policy": "respect",
        "end_behavior": "keep_state",
        "clarifications": clarifications,
        "rules": rules,
    }
    normalized = validate_plan_spec(spec)
    explanation = "仅编译用户明确提出的条件与动作；计划结束保持设备当前状态，手动操作只覆盖对应执行器。"
    return normalized, explanation
