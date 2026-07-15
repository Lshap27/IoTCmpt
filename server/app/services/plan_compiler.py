from __future__ import annotations

import re
from typing import Any

from app.domain.automation_plans import validate_plan_spec


def _seconds(value: int, unit: str) -> int:
    return value * (3600 if unit in {"小时", "hour", "hours"} else 60)


def compile_mock_plan(goal: str, *, timezone: str = "Asia/Shanghai") -> tuple[dict[str, Any], str]:
    """Compile the supported Chinese demo grammar without bypassing plan validation."""
    duration_seconds: int | None = None
    for match in re.finditer(r"(\d+)\s*(分钟|小时|minutes?|hours?)", goal, re.IGNORECASE):
        prefix = goal[max(0, match.start() - 2) : match.start()]
        if "每" not in prefix.lower():
            duration_seconds = _seconds(int(match.group(1)), match.group(2).lower())
            break

    clarifications: list[str] = []
    if duration_seconds is None:
        duration_seconds = 3600
        clarifications.append("请确认计划持续时间")
    elif not 60 <= duration_seconds <= 86400:
        clarifications.append("计划持续时间必须在 1 分钟到 24 小时之间")
    duration_seconds = max(60, min(duration_seconds, 86400))

    rules: list[dict[str, Any]] = []
    if any(keyword in goal for keyword in ("光线暗", "光照暗", "太暗", "暗就开灯")):
        rules.append(
            {
                "id": "dark-lighting",
                "description": "光线持续偏暗时开启照明",
                "trigger": {
                    "type": "condition",
                    "mode": "all",
                    "items": [{"fact": "light_is_dark", "op": "eq", "value": True}],
                    "stability_samples": 2,
                },
                "action": {"command": "led.on", "parameter": {}},
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
    interval = re.search(r"每\s*(\d+)\s*(分钟|小时)", goal)
    if interval:
        interval_seconds = _seconds(int(interval.group(1)), interval.group(2))
        if 60 <= interval_seconds <= 86400:
            rules.append(
                {
                    "id": "activity-reminder",
                    "description": f"每 {interval.group(1)} {interval.group(2)}提醒起身活动",
                    "trigger": {"type": "interval", "every_seconds": interval_seconds},
                    "action": {
                        "command": "voice.speak",
                        "parameter": {},
                        "text": "请起身活动一下，放松肩颈。",
                    },
                    "cooldown_seconds": 0,
                }
            )
        else:
            clarifications.append("提醒间隔必须在 1 分钟到 24 小时之间")
    if not rules:
        clarifications.append("请说明需要执行的光照、通风或提醒动作")

    spec = {
        "schema_version": "1.0",
        "title": "AI 学习自动化计划" if "学习" in goal else "AI 自动化计划",
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
