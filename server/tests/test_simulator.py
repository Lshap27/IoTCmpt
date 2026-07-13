from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType


def load_simulator() -> ModuleType:
    path = Path(__file__).parents[2] / "tools" / "simulate-device.py"
    spec = importlib.util.spec_from_file_location("aiot_device_simulator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_device(scenario: str = "normal"):
    module = load_simulator()
    args = argparse.Namespace(scenario=scenario, device_id="esp32s3-test")
    return module.SimulatedDevice(args)


def test_simulator_telemetry_fluctuates_in_every_scenario():
    for scenario in ("normal", "air-alert", "smoke"):
        device = make_device(scenario)
        samples = [device.telemetry()["sensors"] for _ in range(6)]
        for metric in ("temperature_c", "humidity_percent", "tvoc_ppb", "hcho_ug_m3", "eco2_ppm"):
            assert len({sample[metric] for sample in samples}) > 1, (scenario, metric)


def test_simulator_supports_priority_and_manual_lock_release():
    device = make_device()
    assert device.apply_command({"type": "window.open", "source": "frontend"})[0] == "executed"
    assert device.state["manual_window_override"] is True

    status, _ = device.apply_command({"type": "control.set_priority", "parameter": {"priority": "auto_first"}})
    assert status == "executed"
    assert device.state["control_priority"] == "auto_first"
    assert device.state["manual_window_override"] is False

    device.apply_command({"type": "led.on", "source": "frontend"})
    assert device.state["manual_led_override"] is False
    device.apply_command({"type": "control.set_priority", "parameter": {"priority": "manual_first"}})
    device.apply_command({"type": "led.off", "source": "frontend"})
    assert device.state["manual_led_override"] is True
    assert device.apply_command({"type": "control.resume_auto"})[0] == "executed"
    assert device.state["manual_override"] is False


def test_simulator_smoke_silence_updates_authoritative_state():
    device = make_device("smoke")
    assert device.telemetry()["state"]["alarm_on"] is True
    status, _ = device.apply_command({"type": "alarm.silence", "parameter": {"seconds": 60}})
    assert status == "executed"
    state = device.telemetry()["state"]
    assert state["smoke_silenced"] is True
    assert state["alarm_on"] is False
