from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_THRESHOLDS: dict[str, float] = {
    "temperature_c": 1.0,
    "humidity_percent": 5.0,
    "eco2_ppm": 100.0,
    "tvoc_ppb": 50.0,
    "hcho_ug_m3": 10.0,
}


@dataclass(frozen=True, slots=True)
class PatrolDecision:
    should_call_model: bool
    reason: str
    fingerprint: dict[str, Any]


def build_fingerprint(snapshot: dict[str, Any]) -> dict[str, Any]:
    telemetry = snapshot.get("telemetry") or {}
    sensors = telemetry.get("sensors") or {}
    state = telemetry.get("state") or {}
    fusion = telemetry.get("fusion") or {}
    pose = snapshot.get("pose") or {}
    return {
        "air_quality": fusion.get("air_quality"),
        "smoke_detected": sensors.get("smoke_detected"),
        "human_present": pose.get("human_present"),
        "posture_code": pose.get("posture_code"),
        "window_open": state.get("window_open"),
        "alarm_on": state.get("alarm_on"),
        "led_on": state.get("led_on"),
        "control_priority": state.get("control_priority"),
        **{name: sensors.get(name) for name in DEFAULT_THRESHOLDS},
    }


def evaluate_patrol(
    snapshot: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    last_model_run_at: datetime | None,
    force_interval_seconds: int,
    now: datetime | None = None,
    thresholds: dict[str, float] | None = None,
) -> PatrolDecision:
    current = build_fingerprint(snapshot)
    if previous is None:
        return PatrolDecision(True, "initial", current)
    now = now or datetime.now(UTC).replace(tzinfo=None)
    if last_model_run_at is None or (now - last_model_run_at).total_seconds() >= force_interval_seconds:
        return PatrolDecision(True, "force_interval", current)
    categorical = {
        "air_quality",
        "smoke_detected",
        "human_present",
        "posture_code",
        "window_open",
        "alarm_on",
        "led_on",
        "control_priority",
    }
    if any(current.get(name) != previous.get(name) for name in categorical):
        return PatrolDecision(True, "state_changed", current)
    effective_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    for name, threshold in effective_thresholds.items():
        old, new = previous.get(name), current.get(name)
        if old is not None and new is not None and abs(float(new) - float(old)) >= threshold:
            return PatrolDecision(True, f"{name}_changed", current)
    return PatrolDecision(False, "unchanged", current)
