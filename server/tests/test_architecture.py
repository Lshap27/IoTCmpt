from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db import models
from app.domain.commands import CommandRejected, CommandRequest
from app.schemas import TelemetryIn
from app.services.telemetry import record_telemetry

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
FORBIDDEN_PREFIXES = ("fastapi", "sqlalchemy", "aiomqtt", "mcp", "httpx")


def test_domain_and_application_do_not_import_framework_adapters():
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in (SERVER_ROOT / "app" / layer).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.startswith(FORBIDDEN_PREFIXES) or name.startswith("app.adapters"):
                        violations.append(f"{path.relative_to(SERVER_ROOT)} imports {name}")
    assert not violations, "\n".join(violations)


def test_generated_contracts_are_current_and_have_no_pseudo_command():
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "generate-contracts.py"), "--check"],
        cwd=REPO_ROOT,
        check=True,
    )
    catalog = json.loads((REPO_ROOT / "contracts" / "commands.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in catalog["commands"]}
    assert "none" not in names
    assert "display.message" in names


def test_v1_command_idempotency_and_capabilities(client):
    body = {
        "type": "window.open",
        "parameter": {},
        "reason": "test",
        "idempotency_key": "same-request",
    }
    first = client.post("/api/v1/devices/device-v2/commands", json=body)
    second = client.post("/api/v1/devices/device-v2/commands", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["command_id"] == second.json()["command_id"]
    assert first.json()["trace_id"]

    capabilities = client.get("/api/v1/devices/device-v2/capabilities")
    assert capabilities.status_code == 404


def test_persistent_automation_policy_validates_intervals(client):
    response = client.put(
        "/api/v1/devices/patrol-device/automation-policy",
        json={
            "enabled": True,
            "patrol_enabled": True,
            "patrol_interval_seconds": 300,
            "patrol_force_interval_seconds": 3600,
        },
    )
    assert response.status_code == 200
    assert response.json()["patrol_enabled"] is True
    assert client.get("/api/v1/devices/patrol-device/automation-policy").json()["patrol_interval_seconds"] == 300
    invalid = client.put(
        "/api/v1/devices/patrol-device/automation-policy",
        json={"patrol_interval_seconds": 600, "patrol_force_interval_seconds": 300},
    )
    assert invalid.status_code == 422


def test_ai_run_is_persisted_for_independent_worker(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="ai-device",
                sensors={"temperature_c": 30, "humidity_percent": 70, "eco2_ppm": 1600},
                state={"window_open": False, "alarm_on": False, "led_on": False},
                fusion={"air_quality": "alert", "reason": "test alert"},
            ),
        )
        db.add(
            models.DeviceCapability(
                device_id="ai-device",
                protocol_version="2.0",
                firmware_version="test",
                hardware_model="simulator",
                commands=[{"name": "window.open", "parameter_schema": {}, "safety_class": "normal"}],
            )
        )
        db.commit()

    created = client.post(
        "/api/v1/devices/ai-device/ai/runs",
        json={"kind": "decision", "trigger": "manual"},
    )
    assert created.status_code == 202
    run = created.json()
    assert run["status"] == "queued"
    assert not hasattr(client.app.state, "ai_worker")
    listed = client.get("/api/v1/devices/ai-device/ai/runs").json()
    assert [item["run_id"] for item in listed] == [run["run_id"]]


def test_external_mcp_is_closed_when_not_configured(client):
    response = client.get("/mcp/", headers={"accept": "text/event-stream"})
    assert response.status_code == 503


def test_internal_mcp_bypasses_external_host_filter(client):
    response = client.post(
        "/mcp/",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "host": "server:8000",
            "x-aiot-internal-token": "test-internal-token",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "IoTCmpt Device Tools"


def test_ai_command_still_obeys_server_safety_interlock(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="smoke-device",
                sensors={"smoke_detected": True},
                state={"window_open": True, "alarm_on": True},
                fusion={"air_quality": "alert", "reason": "smoke"},
            ),
        )
        db.add(
            models.DeviceCapability(
                device_id="smoke-device",
                commands=[{"name": "window.close"}],
            )
        )
        db.commit()

    with pytest.raises(CommandRejected, match="smoke") as raised:
        asyncio.run(
            client.app.state.command_application.submit(
                CommandRequest(device_id="smoke-device", type="window.close", source="ai"),
                ai_restricted=True,
            )
        )
    assert raised.value.error_code == "safety_interlock"


def test_outbox_marks_expired_and_ack_timeout_commands(client):
    from app.db.session import SessionLocal

    expired = client.post(
        "/api/v1/devices/lifecycle-device/commands",
        json={"type": "led.on", "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
    ).json()
    timed_out = client.post(
        "/api/v1/devices/lifecycle-device/commands",
        json={"type": "led.off"},
    ).json()
    with SessionLocal() as db:
        first = db.query(models.Command).filter(models.Command.command_id == expired["command_id"]).one()
        first.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        second = db.query(models.Command).filter(models.Command.command_id == timed_out["command_id"]).one()
        second.status = "published"
        second.published_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=2)
        db.commit()

    client.app.state.outbox_dispatcher._expire_and_timeout()
    with SessionLocal() as db:
        statuses = {
            row.command_id: row.status
            for row in db.query(models.Command)
            .filter(models.Command.command_id.in_([expired["command_id"], timed_out["command_id"]]))
            .all()
        }
    assert statuses == {
        expired["command_id"]: "expired",
        timed_out["command_id"]: "timed_out",
    }
