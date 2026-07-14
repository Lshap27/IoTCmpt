from __future__ import annotations

import json
import math
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .generated_behavior import (
    FUSION_THRESHOLDS,
    TERMINAL_ACK_CACHE_SIZE,
)

ROOT = Path(__file__).resolve().parents[2]
COMMAND_CATALOG_DOCUMENT = json.loads(
    (ROOT / "contracts" / "commands.json").read_text(encoding="utf-8")
)
COMMAND_DEFAULTS = COMMAND_CATALOG_DOCUMENT.get("defaults", {})
COMMAND_CATALOG = {
    item["name"]: {**COMMAND_DEFAULTS, **item}
    for item in COMMAND_CATALOG_DOCUMENT["commands"]
}
SCENARIOS = ("normal", "air-watch", "air-alert", "smoke")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def _above(value: float | int, metric: str, level: str) -> bool:
    return value > FUSION_THRESHOLDS[metric][level]


def fuse_sample(sensors: dict[str, Any]) -> dict[str, Any]:
    """Port of firmware/esp32s3/main/fusion/fusion.c."""

    bad = False
    watch = False
    ventilation_needed = False
    reasons: list[str] = []

    temperature = float(sensors["temperature_c"])
    humidity = float(sensors["humidity_percent"])
    tvoc = int(sensors["tvoc_ppb"])
    hcho = int(sensors["hcho_ug_m3"])
    eco2 = int(sensors["eco2_ppm"])

    if _above(temperature, "temperature_c", "alert_above"):
        bad = ventilation_needed = True
        reasons.append(f"温度严重偏高 {temperature:.1f}C")
    elif _above(temperature, "temperature_c", "watch_above"):
        watch = ventilation_needed = True
        reasons.append(f"温度偏高 {temperature:.1f}C")

    humidity_threshold = FUSION_THRESHOLDS["humidity_percent"]
    if (
        humidity > humidity_threshold["watch_above"]
        or humidity < humidity_threshold["watch_below"]
    ):
        watch = ventilation_needed = True
        reasons.append(f"湿度异常 {humidity:.1f}%")

    for metric, value, label in (
        ("tvoc_ppb", tvoc, "TVOC"),
        ("hcho_ug_m3", hcho, "HCHO"),
        ("eco2_ppm", eco2, "eCO2"),
    ):
        if _above(value, metric, "alert_above"):
            bad = ventilation_needed = True
            reasons.append(f"{label} 严重偏高 {value}")
        elif _above(value, metric, "watch_above"):
            watch = ventilation_needed = True
            reasons.append(f"{label} 偏高 {value}")

    if sensors.get("light_is_dark"):
        reasons.append("光照偏暗")
    smoke = bool(sensors.get("smoke_detected"))
    if smoke:
        bad = True
        reasons.append("MQ-2 检测到烟雾")

    if bad:
        quality = "alert"
        recommend = ventilation_needed
        alarm = smoke
    elif watch:
        quality = "watch"
        recommend = True
        alarm = False
    else:
        quality = "good"
        recommend = False
        alarm = False
        reasons = ["空气质量良好"]
    return {
        "air_quality": quality,
        "recommend_open_window": recommend,
        "alarm_enabled": alarm,
        "reason": "；".join(reasons),
    }


class ScenarioSensor:
    def __init__(self, scenario: str):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario}")
        self.scenario = scenario
        self.sequence = 0

    def sample(self) -> dict[str, Any]:
        self.sequence += 1
        slow = math.sin(self.sequence * 0.43)
        fast = math.sin(self.sequence * 0.91 + 0.7)
        if self.scenario == "air-watch":
            base = (29.4, 71.0, 410, 72, 1180, True, False)
            spread = (0.4, 1.2, 24, 4, 55)
        elif self.scenario == "air-alert":
            base = (33.6, 77.0, 720, 112, 1650, True, False)
            spread = (0.4, 1.2, 35, 6, 70)
        elif self.scenario == "smoke":
            base = (25.0, 55.0, 180, 25, 520, False, True)
            spread = (0.4, 1.5, 18, 3, 32)
        else:
            base = (24.8, 52.0, 140, 20, 480, False, False)
            spread = (0.6, 2.2, 16, 3, 38)
        return {
            "temperature_c": round(base[0] + slow * spread[0], 1),
            "humidity_percent": round(base[1] + fast * spread[1], 1),
            "tvoc_ppb": round(base[2] + slow * spread[2]),
            "hcho_ug_m3": round(base[3] + fast * spread[3]),
            "eco2_ppm": round(base[4] + slow * spread[4]),
            "light_is_dark": base[5],
            "smoke_detected": base[6],
        }


class FirmwareModel:
    def __init__(
        self,
        device_id: str,
        scenario: str = "normal",
        nvs: dict[str, Any] | None = None,
    ):
        self.device_id = device_id
        self.scenario = scenario
        self.sensor = ScenarioSensor(scenario)
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.telemetry_count = 0
        self.command_count = 0
        self.image_count = 0
        self.manual_alarm_on = False
        self.smoke_silenced_until = 0.0
        self.last_voice_content: str | None = None
        self.last_display_content: str | None = None
        self.last_telemetry: dict[str, Any] | None = None
        self.last_command: dict[str, Any] | None = None
        stored = nvs or {}
        priority = stored.get("control_priority", "manual_first")
        self.state: dict[str, Any] = {
            "window_open": False,
            "alarm_on": False,
            "manual_override": False,
            "manual_window_override": False,
            "manual_led_override": False,
            "control_priority": priority
            if priority in {"manual_first", "auto_first"}
            else "manual_first",
            "smoke_silenced": False,
            "led_on": False,
        }
        self.terminal_acks: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for item in stored.get("terminal_acks", []):
            if isinstance(item, dict) and item.get("command_id"):
                self.terminal_acks[str(item["command_id"])] = item
        while len(self.terminal_acks) > TERMINAL_ACK_CACHE_SIZE:
            self.terminal_acks.popitem(last=False)

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocol_version": COMMAND_CATALOG_DOCUMENT["schema_version"],
            "firmware_version": "2.0.0",
            "hardware_model": "ESP32-S3-DevKitC-1",
            "commands": [
                {
                    "name": command["name"],
                    "parameter_schema": command["parameter_schema"],
                    "safety_class": command["safety_class"],
                    "ai_allowed": command["ai_allowed"],
                }
                for command in COMMAND_CATALOG_DOCUMENT["commands"]
            ],
        }

    def telemetry(self) -> dict[str, Any]:
        sensors = self.sensor.sample()
        fusion = fuse_sample(sensors)
        smoke_active = bool(sensors["smoke_detected"])
        silence_active = smoke_active and time.monotonic() < self.smoke_silenced_until
        if not smoke_active:
            self.smoke_silenced_until = 0.0
        self.state["smoke_silenced"] = silence_active
        self.state["alarm_on"] = self.manual_alarm_on or (
            smoke_active and not silence_active
        )
        if (
            self.state["control_priority"] == "auto_first"
            and fusion["recommend_open_window"]
            and not self.state["manual_window_override"]
        ):
            self.state["window_open"] = True
        self._refresh_override()
        payload = {
            "device_id": self.device_id,
            "sampled_at": iso_now(),
            "sensors": sensors,
            "state": dict(self.state),
            "fusion": fusion,
        }
        self.telemetry_count += 1
        self.last_telemetry = payload
        return payload

    def validate_command(
        self, envelope: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[str, str] | None:
        if envelope.get("schema_version") != "2.0" or envelope.get("device_id") not in {
            None,
            self.device_id,
        }:
            return "invalid_parameter", "invalid MQTT v2 envelope"
        command_id = payload.get("command_id")
        if (
            not isinstance(command_id, str)
            or not command_id.strip()
            or len(command_id) > 128
        ):
            return "invalid_parameter", "command_id must be a non-empty string"
        command_type = payload.get("type")
        command = COMMAND_CATALOG.get(str(command_type))
        if command is None:
            return "unsupported_command", f"unsupported command: {command_type}"
        source = payload.get("source")
        if source not in command["allowed_sources"]:
            return (
                "policy_denied",
                f"source {source!r} is not allowed for {command_type}",
            )
        parameter = payload.get("parameter", {})
        if not isinstance(parameter, dict):
            return "invalid_parameter", "parameter must be an object"
        error = _validate_parameter(parameter, command["parameter_schema"])
        if error:
            return "invalid_parameter", error
        expires_at = payload.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
            except ValueError:
                return "invalid_parameter", "expires_at must be an ISO-8601 timestamp"
            if expiry <= utc_now():
                return "expired", "command has expired"
        return None

    def apply_command(self, payload: dict[str, Any]) -> tuple[str, str, str | None]:
        command = str(payload["type"])
        parameter = payload.get("parameter") or {}
        source = str(payload["source"])
        automatic_source = source in {"ai", "external_mcp", "rule"}
        if command.startswith("window."):
            if (
                automatic_source
                and self.state["control_priority"] == "manual_first"
                and self.state["manual_window_override"]
            ):
                return "rejected", "manual window override is active", "policy_denied"
            self.state["window_open"] = command == "window.open"
            if (
                source == "frontend"
                and self.state["control_priority"] == "manual_first"
            ):
                self.state["manual_window_override"] = True
        elif command.startswith("led."):
            if (
                automatic_source
                and self.state["control_priority"] == "manual_first"
                and self.state["manual_led_override"]
            ):
                return "rejected", "manual LED override is active", "policy_denied"
            self.state["led_on"] = command == "led.on"
            if (
                source == "frontend"
                and self.state["control_priority"] == "manual_first"
            ):
                self.state["manual_led_override"] = True
        elif command == "alarm.on":
            self.manual_alarm_on = True
            self.state["alarm_on"] = True
        elif command == "alarm.off":
            self.manual_alarm_on = False
            self.state["alarm_on"] = bool(
                self.last_telemetry
                and self.last_telemetry["sensors"]["smoke_detected"]
                and not self.state["smoke_silenced"]
            )
        elif command == "control.set_priority":
            self.state["control_priority"] = parameter["priority"]
            if parameter["priority"] == "auto_first":
                self.state["manual_window_override"] = False
                self.state["manual_led_override"] = False
        elif command == "control.resume_auto":
            self.state["manual_window_override"] = False
            self.state["manual_led_override"] = False
        elif command == "alarm.silence":
            smoke_active = bool(
                self.last_telemetry and self.last_telemetry["sensors"]["smoke_detected"]
            )
            if not smoke_active:
                return "rejected", "no active smoke alarm", "safety_interlock"
            duration = int(parameter.get("duration_seconds", 60))
            self.smoke_silenced_until = time.monotonic() + duration
            self.state["smoke_silenced"] = True
            self.state["alarm_on"] = self.manual_alarm_on
        elif command == "voice.speak":
            self.last_voice_content = str(parameter["gb2312_base64"])
        elif command == "display.message":
            self.last_display_content = str(parameter["text"])
        self.command_count += 1
        self._refresh_override()
        return "executed", f"{command} executed by firmware simulator", None

    def remember_terminal_ack(self, ack: dict[str, Any]) -> None:
        command_id = str(ack["command_id"])
        self.terminal_acks.pop(command_id, None)
        self.terminal_acks[command_id] = ack
        while len(self.terminal_acks) > TERMINAL_ACK_CACHE_SIZE:
            self.terminal_acks.popitem(last=False)
        self.last_command = dict(ack)

    def nvs_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "control_priority": self.state["control_priority"],
            "terminal_acks": list(self.terminal_acks.values()),
        }

    def _refresh_override(self) -> None:
        self.state["manual_override"] = bool(
            self.state["manual_window_override"] or self.state["manual_led_override"]
        )


def _validate_parameter(
    parameter: dict[str, Any], schema: dict[str, Any]
) -> str | None:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in parameter:
            return f"missing required parameter: {key}"
    if schema.get("additionalProperties") is False:
        unexpected = set(parameter) - set(properties)
        if unexpected:
            return f"unexpected parameter: {sorted(unexpected)[0]}"
    for key, value in parameter.items():
        rule = properties.get(key, {})
        expected = rule.get("type")
        if expected == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return f"{key} must be an integer"
        if expected == "string" and not isinstance(value, str):
            return f"{key} must be a string"
        if "enum" in rule and value not in rule["enum"]:
            return f"{key} must be one of {rule['enum']}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                return f"{key} must be at least {rule['minimum']}"
            if "maximum" in rule and value > rule["maximum"]:
                return f"{key} must be at most {rule['maximum']}"
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]:
                return f"{key} is too short"
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                return f"{key} is too long"
    return None
