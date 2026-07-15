from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adapters.ai_worker import AiRunWorker
from app.adapters.mcp_server import MCP_INTERNAL, MCP_SCOPES, MCP_TRACE_ID
from app.core.config import get_settings
from app.db import models
from app.domain.commands import CommandRejected
from app.schemas import TelemetryIn
from app.services.lighting_automation import LightingAutomationService
from app.services.llm import LLMService
from app.services.telemetry import record_command_ack, record_telemetry
from app.services.voice_commands import encode_voice_text


def structured_tool_result(result):
    return result[1] if isinstance(result, tuple) else result


def seed_lighting_inputs(
    *,
    light_values: tuple[bool, bool],
    human_present: bool,
    led_on: bool,
    policy_enabled: bool = True,
    manual_override: bool = False,
    pose_age_seconds: int = 0,
) -> None:
    from app.db.session import SessionLocal

    now = datetime.now(UTC)
    with SessionLocal() as db:
        for index, light_is_dark in enumerate(light_values):
            record_telemetry(
                db,
                TelemetryIn(
                    device_id="lighting-device",
                    sampled_at=now - timedelta(seconds=1 - index),
                    sensors={"light_is_dark": light_is_dark},
                    state={
                        "led_on": led_on,
                        "control_priority": "manual_first",
                        "manual_led_override": manual_override,
                    },
                ),
            )
        db.add(
            models.DeviceCapability(
                device_id="lighting-device",
                commands=[{"name": "led.on"}, {"name": "led.off"}, {"name": "voice.speak"}],
            )
        )
        image = models.ImageAsset(
            device_id="lighting-device",
            filename="test.jpg",
            url="/uploads/test.jpg",
            content_type="image/jpeg",
            size_bytes=1,
            kind="capture",
        )
        db.add(image)
        db.flush()
        db.add(
            models.PoseResult(
                device_id="lighting-device",
                source_image_id=image.id,
                human_present=human_present,
                confidence=0.99,
                created_at=now.replace(tzinfo=None) - timedelta(seconds=pose_age_seconds),
            )
        )
        db.add(models.AutomationPolicy(device_id="lighting-device", enabled=policy_enabled))
        db.commit()


def test_dark_present_turns_light_on_then_speaks_once_after_executed_ack(client):
    seed_lighting_inputs(light_values=(True, True), human_present=True, led_on=False)
    service = client.app.state.lighting_automation

    led = asyncio.run(service.evaluate("lighting-device"))
    assert led is not None and led["type"] == "led.on" and led["source"] == "rule"
    assert asyncio.run(service.evaluate("lighting-device")) is None

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        command = db.query(models.Command).filter(models.Command.command_id == led["command_id"]).one()
        record_command_ack(
            db,
            SimpleNamespace(
                command_id=command.command_id,
                device_id="lighting-device",
                trace_id=command.trace_id,
                status="executed",
                error_code=None,
                message="ok",
                executed_at=datetime.now(UTC),
                reported_state={"led_on": True},
            ),
        )

    restarted = LightingAutomationService(SessionLocal, client.app.state.command_application)
    assert asyncio.run(restarted.evaluate("lighting-device")) is None
    assert asyncio.run(restarted.reconcile_command("lighting-device", led["command_id"])) is None

    with SessionLocal() as db:
        voices = db.query(models.Command).filter(models.Command.type == "voice.speak").all()
        assert len(voices) == 1
        text = base64.b64decode(voices[0].parameter["gb2312_base64"]).decode("gb2312")
        assert text == "检测到环境光线较暗，已为您打开照明。"


def test_rejected_lighting_command_never_creates_speech(client):
    seed_lighting_inputs(light_values=(True, True), human_present=True, led_on=False)
    service = client.app.state.lighting_automation
    led = asyncio.run(service.evaluate("lighting-device"))
    assert led is not None

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        command = db.query(models.Command).filter(models.Command.command_id == led["command_id"]).one()
        record_command_ack(
            db,
            SimpleNamespace(
                command_id=command.command_id,
                device_id="lighting-device",
                trace_id=command.trace_id,
                status="rejected",
                error_code="policy_denied",
                message="manual priority",
                executed_at=datetime.now(UTC),
                reported_state={"led_on": False},
            ),
        )

    assert asyncio.run(service.reconcile_command("lighting-device", led["command_id"])) is None
    with SessionLocal() as db:
        assert db.query(models.Command).filter(models.Command.type == "voice.speak").count() == 0


@pytest.mark.parametrize(
    ("light_values", "human_present", "led_on", "expected"),
    [
        ((False, False), False, True, "led.off"),
        ((False, False), True, True, None),
        ((True, True), False, False, None),
        ((False, True), True, False, None),
    ],
)
def test_lighting_combinations_and_unstable_light(
    client,
    light_values: tuple[bool, bool],
    human_present: bool,
    led_on: bool,
    expected: str | None,
):
    seed_lighting_inputs(
        light_values=light_values,
        human_present=human_present,
        led_on=led_on,
    )
    result = asyncio.run(client.app.state.lighting_automation.evaluate("lighting-device"))
    assert (result or {}).get("type") == expected


@pytest.mark.parametrize(
    ("policy_enabled", "manual_override", "pose_age_seconds"),
    [(False, False, 0), (True, True, 0), (True, False, 16)],
)
def test_lighting_respects_global_switch_manual_priority_and_pose_freshness(
    client,
    policy_enabled: bool,
    manual_override: bool,
    pose_age_seconds: int,
):
    seed_lighting_inputs(
        light_values=(True, True),
        human_present=True,
        led_on=False,
        policy_enabled=policy_enabled,
        manual_override=manual_override,
        pose_age_seconds=pose_age_seconds,
    )
    assert asyncio.run(client.app.state.lighting_automation.evaluate("lighting-device")) is None


def test_voice_encoding_replaces_unsupported_characters_and_enforces_220_bytes():
    assert base64.b64decode(encode_voice_text("  hello🙂  ")).decode("gb2312") == "hello?"
    assert len(base64.b64decode(encode_voice_text("中" * 110))) == 220
    with pytest.raises(CommandRejected, match="220-byte"):
        encode_voice_text("中" * 111)


def test_device_speak_mcp_uses_source_capability_and_idempotency(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(db, TelemetryIn(device_id="speech-device"))
        db.add(models.DeviceCapability(device_id="speech-device", commands=[{"name": "voice.speak"}]))
        db.commit()

    async def call(*, internal: bool, key: str):
        scope_token = MCP_SCOPES.set(frozenset({"mcp:read", "mcp:control"}))
        internal_token = MCP_INTERNAL.set(internal)
        trace_token = MCP_TRACE_ID.set("trace-speech-test")
        try:
            return structured_tool_result(
                await client.app.state.mcp_server.call_tool(
                    "device_speak",
                    {
                        "device_id": "speech-device",
                        "text": "请注意休息。",
                        "reason": "test",
                        "idempotency_key": key,
                    },
                )
            )
        finally:
            MCP_TRACE_ID.reset(trace_token)
            MCP_INTERNAL.reset(internal_token)
            MCP_SCOPES.reset(scope_token)

    first = asyncio.run(call(internal=True, key="same"))
    replay = asyncio.run(call(internal=True, key="same"))
    with SessionLocal() as db:
        command = db.query(models.Command).filter(models.Command.command_id == first["data"]["command_id"]).one()
        command.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        db.commit()
    external = asyncio.run(call(internal=False, key="external"))
    assert first["ok"] and replay["data"]["command_id"] == first["data"]["command_id"]
    assert external["ok"]

    with SessionLocal() as db:
        rows = db.query(models.Command).filter(models.Command.device_id == "speech-device").all()
        assert sorted(row.source for row in rows) == ["ai", "external_mcp"]


def test_device_speak_mcp_rejects_offline_or_unknown_capability(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(db, TelemetryIn(device_id="unknown-capability"))
        db.add(models.Device(device_id="offline-device", status="offline"))
        db.add(models.DeviceCapability(device_id="offline-device", commands=[{"name": "voice.speak"}]))
        db.commit()

    async def call(device_id: str):
        scope_token = MCP_SCOPES.set(frozenset({"mcp:read", "mcp:control"}))
        internal_token = MCP_INTERNAL.set(True)
        try:
            return structured_tool_result(
                await client.app.state.mcp_server.call_tool(
                    "device_speak",
                    {"device_id": device_id, "text": "测试", "reason": "test"},
                )
            )
        finally:
            MCP_INTERNAL.reset(internal_token)
            MCP_SCOPES.reset(scope_token)

    assert asyncio.run(call("unknown-capability"))["error"]["code"] == "unsupported_command"
    assert asyncio.run(call("offline-device"))["error"]["code"] == "device_offline"


@pytest.mark.parametrize(
    ("kind", "run_input", "snapshot", "should_speak"),
    [
        (
            "decision",
            {"event_type": "posture.sedentary", "goal": "处理久坐事件"},
            {"telemetry": {"sensors": {}, "state": {}, "fusion": {}}, "pose": {"human_present": True}},
            True,
        ),
        (
            "patrol",
            {},
            {
                "telemetry": {"sensors": {}, "state": {"window_open": True}, "fusion": {"air_quality": "alert"}},
                "air_trend": "worsening",
            },
            True,
        ),
        (
            "decision",
            {"goal": "请语音播报当前提醒"},
            {"telemetry": {"sensors": {}, "state": {}, "fusion": {}}},
            True,
        ),
        (
            "decision",
            {"event_type": "smoke.detected", "goal": "处理烟雾事件"},
            {
                "telemetry": {
                    "sensors": {"smoke_detected": True},
                    "state": {"alarm_on": True},
                    "fusion": {"air_quality": "alert"},
                }
            },
            False,
        ),
    ],
)
def test_mock_worker_executes_only_intended_speech(kind, run_input, snapshot, should_speak):
    worker = AiRunWorker.__new__(AiRunWorker)
    worker.settings = SimpleNamespace(llm_endpoint="mock")
    worker.llm = LLMService(get_settings())
    worker._transition = AsyncMock()
    worker._call_tool = AsyncMock(return_value={"ok": True, "data": {"status": "executed"}})
    run = {
        "run_id": "run-test",
        "trace_id": "trace-test",
        "device_id": "device-test",
        "kind": kind,
        "input": run_input,
    }

    output = asyncio.run(worker._execute_mock_tool_run(run, snapshot))
    calls = [call.args[2] for call in worker._call_tool.await_args_list]
    assert ("device_speak" in calls) is should_speak
    assert ("speech_action" in output) is should_speak
