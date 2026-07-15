from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.generated.command_catalog import AI_COMMAND_NAMES, COMMAND_CATALOG

PLAN_SCHEMA_VERSION = "1.0"
PLAN_STATUSES = {"draft", "active", "paused", "completed", "cancelled", "failed", "superseded"}
ACTIVE_PLAN_STATUSES = {"active", "paused"}
PLAN_TYPES = {"system", "user"}
PLAN_FACTS = {
    "light_is_dark",
    "human_present",
    "air_quality",
    "temperature_c",
    "humidity_percent",
    "tvoc_ppb",
    "hcho_ug_m3",
    "eco2_ppm",
    "window_open",
    "led_on",
    "device_status",
}
NUMERIC_FACTS = {
    "temperature_c",
    "humidity_percent",
    "tvoc_ppb",
    "hcho_ug_m3",
    "eco2_ppm",
}
PLAN_OPERATORS = {"eq", "in", "gt", "gte", "lt", "lte"}
SAFE_PLAN_COMMANDS = set(AI_COMMAND_NAMES)
RULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _validate_predicate(predicate: Any) -> dict[str, Any]:
    if not isinstance(predicate, dict):
        raise ValueError("condition item must be an object")
    if set(predicate) != {"fact", "op", "value"}:
        raise ValueError("condition item accepts only fact, op and value")
    fact = str(predicate.get("fact") or "")
    op = str(predicate.get("op") or "")
    value = predicate.get("value")
    if fact not in PLAN_FACTS:
        raise ValueError(f"unsupported automation fact: {fact}")
    if op not in PLAN_OPERATORS:
        raise ValueError(f"unsupported automation operator: {op}")
    if op in {"gt", "gte", "lt", "lte"} and (
        fact not in NUMERIC_FACTS or isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise ValueError(f"{op} requires a numeric fact and value")
    if op == "in" and (not isinstance(value, list) or not 1 <= len(value) <= 8):
        raise ValueError("in requires a list with 1..8 values")
    return {"fact": fact, "op": op, "value": value}


def _validate_trigger(trigger: Any) -> dict[str, Any]:
    if not isinstance(trigger, dict):
        raise ValueError("rule trigger must be an object")
    trigger_type = str(trigger.get("type") or "")
    if trigger_type == "condition":
        if set(trigger) != {"type", "mode", "items", "stability_samples"}:
            raise ValueError("condition trigger contains unsupported fields")
        mode = str(trigger.get("mode") or "")
        if mode not in {"all", "any"}:
            raise ValueError("condition mode must be all or any")
        items = trigger.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ValueError("condition trigger requires 1..8 items")
        return {
            "type": "condition",
            "mode": mode,
            "items": [_validate_predicate(item) for item in items],
            "stability_samples": _integer(trigger.get("stability_samples"), "stability_samples", 1, 5),
        }
    if trigger_type == "interval":
        if set(trigger) != {"type", "every_seconds"}:
            raise ValueError("interval trigger contains unsupported fields")
        return {
            "type": "interval",
            "every_seconds": _integer(trigger.get("every_seconds"), "every_seconds", 60, 86400),
        }
    raise ValueError(f"unsupported automation trigger: {trigger_type}")


def _validate_action(action: Any) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ValueError("rule action must be an object")
    if not {"command", "parameter"}.issubset(action) or set(action) - {"command", "parameter", "text"}:
        raise ValueError("action accepts only command, parameter and text")
    command = str(action.get("command") or "")
    if command not in SAFE_PLAN_COMMANDS:
        raise ValueError(f"command is not AI-safe: {command}")
    parameter = action.get("parameter")
    if not isinstance(parameter, dict):
        raise ValueError("action parameter must be an object")
    text = action.get("text")
    if command == "voice.speak":
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 60:
            raise ValueError("voice.speak requires text with 1..60 characters")
        parameter = {}
    elif command == "display.message":
        if text is not None:
            parameter = {"text": str(text).strip()}
        display_text = parameter.get("text")
        if not isinstance(display_text, str) or not 1 <= len(display_text) <= 120:
            raise ValueError("display.message requires text with 1..120 characters")
    elif text is not None:
        raise ValueError("text is only valid for voice.speak or display.message")
    expected: dict[str, Any] = (
        {"additionalProperties": False, "properties": {}}
        if command == "voice.speak"
        else COMMAND_CATALOG[command]["parameter_schema"]
    )
    if expected.get("additionalProperties") is False:
        allowed = set((expected.get("properties") or {}).keys())
        if set(parameter) - allowed:
            raise ValueError(f"unsupported parameters for {command}")
        for required in expected.get("required") or []:
            if required not in parameter:
                raise ValueError(f"missing {required} for {command}")
    result: dict[str, Any] = {"command": command, "parameter": parameter}
    if command == "voice.speak":
        result["text"] = str(text).strip()
    elif command == "display.message":
        result["text"] = str(parameter["text"])
    return result


def validate_plan_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("automation plan must be an object")
    required = {
        "schema_version",
        "title",
        "duration_seconds",
        "timezone",
        "manual_override_policy",
        "end_behavior",
        "clarifications",
        "rules",
    }
    if set(spec) != required:
        raise ValueError(f"automation plan fields must be exactly {sorted(required)}")
    if spec.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported automation plan schema version")
    title = str(spec.get("title") or "").strip()
    if not 1 <= len(title) <= 120:
        raise ValueError("plan title must have 1..120 characters")
    timezone = str(spec.get("timezone") or "").strip()
    if not 1 <= len(timezone) <= 64:
        raise ValueError("plan timezone must have 1..64 characters")
    if spec.get("manual_override_policy") != "respect":
        raise ValueError("manual_override_policy must be respect")
    if spec.get("end_behavior") != "keep_state":
        raise ValueError("end_behavior must be keep_state")
    clarifications = spec.get("clarifications")
    if not isinstance(clarifications, list) or len(clarifications) > 5:
        raise ValueError("clarifications must contain at most 5 items")
    normalized_clarifications: list[str] = []
    for item in clarifications:
        text = str(item).strip()
        if not 1 <= len(text) <= 240:
            raise ValueError("clarification must have 1..240 characters")
        normalized_clarifications.append(text)
    rules = spec.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 16:
        raise ValueError("automation plan requires 1..16 rules")
    normalized_rules: list[dict[str, Any]] = []
    rule_ids: set[str] = set()
    for raw in rules:
        if not isinstance(raw, dict):
            raise ValueError("plan rule must be an object")
        if set(raw) != {"id", "description", "trigger", "action", "cooldown_seconds"}:
            raise ValueError("plan rule contains unsupported fields")
        rule_id = str(raw.get("id") or "")
        if not RULE_ID_RE.fullmatch(rule_id) or rule_id in rule_ids:
            raise ValueError(f"invalid or duplicate rule id: {rule_id}")
        rule_ids.add(rule_id)
        description = str(raw.get("description") or "").strip()
        if not 1 <= len(description) <= 240:
            raise ValueError("rule description must have 1..240 characters")
        normalized_rules.append(
            {
                "id": rule_id,
                "description": description,
                "trigger": _validate_trigger(raw.get("trigger")),
                "action": _validate_action(raw.get("action")),
                "cooldown_seconds": _integer(raw.get("cooldown_seconds"), "cooldown_seconds", 0, 86400),
            }
        )
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "title": title,
        "duration_seconds": _integer(spec.get("duration_seconds"), "duration_seconds", 60, 86400),
        "timezone": timezone,
        "manual_override_policy": "respect",
        "end_behavior": "keep_state",
        "clarifications": normalized_clarifications,
        "rules": normalized_rules,
    }


def plan_actuators(spec: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for rule in spec.get("rules") or []:
        command = str((rule.get("action") or {}).get("command") or "")
        if command.startswith("window."):
            result.add("window")
        elif command.startswith("led."):
            result.add("led")
        elif command == "voice.speak":
            result.add("voice")
        elif command == "display.message":
            result.add("display")
    return result


def structural_diff(base: dict[str, Any] | None, proposed: dict[str, Any]) -> list[dict[str, Any]]:
    if base is None:
        return [{"path": "$", "before": None, "after": deepcopy(proposed)}]
    changes: list[dict[str, Any]] = []

    def walk(path: str, before: Any, after: Any) -> None:
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                walk(f"{path}.{key}", before.get(key), after.get(key))
        elif before != after:
            changes.append({"path": path, "before": deepcopy(before), "after": deepcopy(after)})

    walk("$", base, proposed)
    return changes
