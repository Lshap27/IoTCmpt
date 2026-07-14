from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_config", REPO / "tools" / "runtime_config.py")
assert SPEC and SPEC.loader
runtime_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_config)

PANEL_SPEC = importlib.util.spec_from_file_location("panel_server", REPO / "tools" / "panel" / "panel_server.py")
assert PANEL_SPEC and PANEL_SPEC.loader
panel_server = importlib.util.module_from_spec(PANEL_SPEC)
PANEL_SPEC.loader.exec_module(panel_server)


def test_runtime_catalog_generates_secret_and_reports_affected_services(tmp_path, monkeypatch):
    compose = tmp_path / ".env"
    server = tmp_path / "server.env"
    web = tmp_path / "web.env"
    monkeypatch.setattr(
        runtime_config,
        "ENV_PATHS",
        {"compose": compose, "gateway": server, "worker": server, "shared": server, "web": web},
    )

    preview = runtime_config.apply_config({"AIOT_LLM_TIMEOUT_SECONDS": "60"}, dry_run=True)
    assert not compose.exists()
    assert "gateway" in preview["affectedServices"]
    assert "worker" in preview["affectedServices"]
    internal = next(item for item in preview["diff"] if item["key"] == "AIOT_MCP_INTERNAL_TOKEN")
    assert internal["secret"] is True
    assert internal["after"] == "已配置"

    runtime_config.apply_config({"AIOT_LLM_TIMEOUT_SECONDS": "60"})
    values = runtime_config.parse_env(server)
    compose_values = runtime_config.parse_env(compose)
    assert values["AIOT_LLM_TIMEOUT_SECONDS"] == "60"
    assert len(values["AIOT_MCP_INTERNAL_TOKEN"]) >= 32
    assert compose_values["AIOT_MCP_INTERNAL_TOKEN"] == values["AIOT_MCP_INTERNAL_TOKEN"]
    assert "AIOT_AUTOPILOT_ENABLED" not in values


def test_firmware_image_url_examples_are_v1():
    assert "/api/v1/devices/" in (REPO / "firmware" / "esp32s3" / "main" / "Kconfig").read_text(encoding="utf-8")


def test_panel_generates_external_mcp_credentials(monkeypatch):
    captured = {}

    def fake_apply(changes, *, dry_run=False):
        captured.update(changes)
        return {"ok": True, "dryRun": dry_run, "diff": [], "affectedServices": []}

    monkeypatch.setattr(panel_server, "apply_config", fake_apply)
    monkeypatch.setattr(panel_server, "get_env_config", lambda: {"server": {}})

    panel_server.save_env_config(
        {
            "deviceMode": "Simulator",
            "aiMode": "Mock",
            "deviceId": "esp32s3-001",
            "mcpEnabled": True,
        }
    )

    assert captured["AIOT_LLM_TIMEOUT_SECONDS"] == "60"
    assert captured["AIOT_MCP_READ_TOKEN"] == "generated"
    assert captured["AIOT_MCP_CONTROL_TOKEN"] == "generated"


def test_runtime_writer_resolves_external_tokens_independently(tmp_path, monkeypatch):
    compose = tmp_path / ".env"
    server = tmp_path / "server.env"
    web = tmp_path / "web.env"
    monkeypatch.setattr(
        runtime_config,
        "ENV_PATHS",
        {"compose": compose, "gateway": server, "worker": server, "shared": server, "web": web},
    )

    runtime_config.apply_config(
        {
            "AIOT_MCP_READ_TOKEN": "generated",
            "AIOT_MCP_CONTROL_TOKEN": "generated",
        }
    )
    values = runtime_config.parse_env(server)
    assert values["AIOT_MCP_READ_TOKEN"] != values["AIOT_MCP_CONTROL_TOKEN"]


def test_simulator_runtime_values_are_validated(tmp_path, monkeypatch):
    compose = tmp_path / ".env"
    server = tmp_path / "server.env"
    web = tmp_path / "web.env"
    monkeypatch.setattr(
        runtime_config,
        "ENV_PATHS",
        {"compose": compose, "gateway": server, "worker": server, "shared": server, "web": web},
    )
    runtime_config.apply_config(
        {
            "AIOT_DEMO_SCENARIO": "air-watch",
            "AIOT_SIMULATOR_TELEMETRY_INTERVAL_SECONDS": "1",
            "AIOT_SIMULATOR_IMAGE_ENABLED": "false",
            "AIOT_SIMULATOR_IMAGE_INTERVAL_SECONDS": "3600",
        }
    )
    values = runtime_config.parse_env(compose)
    assert values["AIOT_DEMO_SCENARIO"] == "air-watch"
    assert values["AIOT_SIMULATOR_IMAGE_ENABLED"] == "false"
    with pytest.raises(ValueError, match="at least 1"):
        runtime_config.apply_config({"AIOT_SIMULATOR_TELEMETRY_INTERVAL_SECONDS": "0"}, dry_run=True)
    with pytest.raises(ValueError, match="one of"):
        runtime_config.apply_config({"AIOT_DEMO_SCENARIO": "broken"}, dry_run=True)


def test_panel_reads_fresh_simulator_status_and_rejects_stale_or_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(panel_server, "SIMULATOR_STATE_ROOT", tmp_path)
    directory = tmp_path / "esp32s3-test"
    directory.mkdir()
    path = directory / "status.json"
    path.write_text(
        json.dumps({"updated_at": datetime.now(UTC).isoformat(), "mqtt_connected": True}),
        encoding="utf-8",
    )
    assert panel_server.read_simulator_status("esp32s3-test")["ready"] is True

    path.write_text(
        json.dumps({"updated_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}),
        encoding="utf-8",
    )
    assert panel_server.read_simulator_status("esp32s3-test")["reason"] == "状态已过期"
    path.write_text("not-json", encoding="utf-8")
    assert panel_server.read_simulator_status("esp32s3-test")["ready"] is False
