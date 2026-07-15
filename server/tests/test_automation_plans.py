from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.adapters.ai_worker import PatrolScheduler
from app.adapters.automation_plans import SqlAlchemyAutomationPlanRepository, utcnow
from app.adapters.job_store import SqlAlchemyJobStore
from app.adapters.mcp_server import MCP_INTERNAL, MCP_SCOPES, MCP_TRACE_ID
from app.db import models
from app.schemas import TelemetryIn
from app.services.plan_compiler import compile_mock_plan
from app.services.telemetry import record_telemetry


def seed_device(*, manual_window: bool = False, commands: list[str] | None = None) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="plan-device",
                sensors={"light_is_dark": True},
                state={
                    "window_open": False,
                    "led_on": False,
                    "control_priority": "manual_first",
                    "manual_window_override": manual_window,
                },
                fusion={"air_quality": "alert"},
            ),
        )
        db.add(
            models.DeviceCapability(
                device_id="plan-device",
                commands=[
                    {"name": name}
                    for name in (commands or ["window.open", "window.close", "led.on", "led.off", "voice.speak"])
                ],
            )
        )
        db.add(models.AutomationPolicy(device_id="plan-device", enabled=True))
        db.commit()


def test_mock_compiler_keeps_only_requested_actions_and_manual_semantics():
    spec, _ = compile_mock_plan(
        "我要学习 90 分钟。光线暗就开灯，空气不好就通风，每 30 分钟提醒我起来活动，但不要覆盖我的手动操作。"
    )
    assert spec["duration_seconds"] == 5400
    assert spec["manual_override_policy"] == "respect"
    assert spec["end_behavior"] == "keep_state"
    commands = [rule["action"]["command"] for rule in spec["rules"]]
    assert commands == ["led.on", "window.open", "voice.speak"]
    assert not any(command in commands for command in ["led.off", "window.close"])
    assert spec["rules"][2]["trigger"]["every_seconds"] == 1800


def test_auto_activation_and_existing_plan_blocker_are_visible(client):
    seed_device()
    spec, explanation = compile_mock_plan("持续 60 分钟，空气不好就通风")
    service = client.app.state.automation_plan_application
    first = asyncio.run(service.create_draft("plan-device", "goal one", spec, explanation, None, "trace-one"))
    second = asyncio.run(service.create_draft("plan-device", "goal two", spec, explanation, None, "trace-two"))

    assert first["status"] == "active"
    assert first["activation_blockers"] == []
    assert second["status"] == "draft"
    assert second["activation_blockers"] == [f"active_plan:{first['plan_id']}"]
    response = client.get("/api/v1/devices/plan-device/automation-plans")
    assert response.status_code == 200
    assert {plan["plan_id"] for plan in response.json()} >= {first["plan_id"], second["plan_id"]}


def test_manual_override_blocks_once_then_releases_on_state_change(client):
    seed_device(manual_window=True, commands=["window.open", "led.on", "led.off"])
    spec, explanation = compile_mock_plan("持续 60 分钟，空气不好就通风")
    plan = asyncio.run(
        client.app.state.automation_plan_application.create_draft(
            "plan-device", "air goal", spec, explanation, None, "trace-air"
        )
    )
    runtime = client.app.state.automation_runtime

    assert asyncio.run(runtime.evaluate("plan-device")) == []
    assert asyncio.run(runtime.evaluate("plan-device")) == []
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        blocked = (
            db.query(models.AutomationPlanEvent)
            .filter_by(plan_id=plan["plan_id"], event_type="blocked_by_manual_override")
            .count()
        )
        assert blocked == 1
        record_telemetry(
            db,
            TelemetryIn(
                device_id="plan-device",
                state={
                    "window_open": False,
                    "control_priority": "manual_first",
                    "manual_window_override": False,
                },
                fusion={"air_quality": "alert"},
            ),
        )

    commands = asyncio.run(runtime.evaluate("plan-device"))
    assert len(commands) == 1
    assert commands[0]["type"] == "window.open"
    assert commands[0]["source"] == "rule"


def test_manual_override_after_a_fired_edge_is_audited_without_reopening(client):
    seed_device(manual_window=False, commands=["window.open", "led.on", "led.off"])
    spec, explanation = compile_mock_plan("持续 60 分钟，空气不好就通风")
    plan = asyncio.run(
        client.app.state.automation_plan_application.create_draft(
            "plan-device", "air goal", spec, explanation, None, "trace-air-fired"
        )
    )
    runtime = client.app.state.automation_runtime
    assert len(asyncio.run(runtime.evaluate("plan-device"))) == 1
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="plan-device",
                state={
                    "window_open": False,
                    "control_priority": "manual_first",
                    "manual_window_override": True,
                },
                fusion={"air_quality": "alert"},
            ),
        )
    assert asyncio.run(runtime.evaluate("plan-device")) == []
    with SessionLocal() as db:
        assert (
            db.query(models.AutomationPlanEvent)
            .filter_by(plan_id=plan["plan_id"], event_type="blocked_by_manual_override")
            .count()
            == 1
        )
        assert db.query(models.Command).filter_by(device_id="plan-device", type="window.open").count() == 1


def test_restart_style_missed_interval_is_skipped_and_reanchored(client):
    seed_device(commands=["voice.speak", "led.on", "led.off"])
    spec, explanation = compile_mock_plan("持续 60 分钟，每 1 分钟提醒我起来活动")
    plan = asyncio.run(
        client.app.state.automation_plan_application.create_draft(
            "plan-device", "reminder", spec, explanation, None, "trace-reminder"
        )
    )
    from app.db.session import SessionLocal

    now = utcnow()
    with SessionLocal() as db:
        row = db.query(models.AutomationPlan).filter_by(plan_id=plan["plan_id"]).one()
        row.started_at = now - timedelta(minutes=3)
        row.ends_at = now + timedelta(minutes=10)
        state = (
            db.query(models.AutomationRuleState).filter_by(plan_id=plan["plan_id"], rule_id="activity-reminder").one()
        )
        state.next_fire_at = now - timedelta(minutes=2)
        db.commit()

    assert asyncio.run(client.app.state.automation_runtime.evaluate("plan-device", include_conditions=False)) == []
    with SessionLocal() as db:
        state = (
            db.query(models.AutomationRuleState).filter_by(plan_id=plan["plan_id"], rule_id="activity-reminder").one()
        )
        assert state.next_fire_at > now
        assert db.query(models.Command).filter_by(device_id="plan-device", type="voice.speak").count() == 0


def test_strategy_approval_is_version_fenced(client):
    seed_device()
    spec, explanation = compile_mock_plan("持续 60 分钟，空气不好就通风")
    plan = asyncio.run(
        client.app.state.automation_plan_application.create_draft(
            "plan-device", "air", spec, explanation, None, "trace-base"
        )
    )
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        for run_id in ["run-strategy-a", "run-strategy-b"]:
            db.add(
                models.AiRun(
                    run_id=run_id,
                    trace_id=f"trace-{run_id}",
                    device_id="plan-device",
                    kind="strategy",
                    trigger="manual",
                    status="succeeded",
                    input_payload={},
                )
            )
        db.commit()
    repository = SqlAlchemyAutomationPlanRepository(SessionLocal)
    changed_a = {**spec, "title": "策略版本 A"}
    changed_b = {**spec, "title": "策略版本 B"}
    first = repository.propose_strategy("plan-device", "run-strategy-a", plan["plan_id"], 1, changed_a, "rename A")
    second = repository.propose_strategy("plan-device", "run-strategy-b", plan["plan_id"], 1, changed_b, "rename B")
    assert repository.resolve_strategy("plan-device", first["strategy_id"], "approve")["status"] == "approved"
    with pytest.raises(RuntimeError, match="stale"):
        repository.resolve_strategy("plan-device", second["strategy_id"], "approve")


def test_internal_mcp_plan_tool_uses_the_same_validator_and_activation_path(client):
    seed_device()
    spec, explanation = compile_mock_plan("持续 60 分钟，空气不好就通风")
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.add(
            models.AiRun(
                run_id="run-plan-mcp",
                trace_id="trace-plan-mcp",
                device_id="plan-device",
                kind="plan_compile",
                trigger="manual",
                status="running",
                input_payload={"goal": "持续 60 分钟，空气不好就通风"},
            )
        )
        db.commit()

    async def invoke():
        scope_token = MCP_SCOPES.set(frozenset({"mcp:read", "mcp:control"}))
        internal_token = MCP_INTERNAL.set(True)
        trace_token = MCP_TRACE_ID.set("trace-plan-mcp")
        try:
            raw = await client.app.state.mcp_server.call_tool(
                "automation_plan_create_draft",
                {
                    "device_id": "plan-device",
                    "run_id": "run-plan-mcp",
                    "source_prompt": "持续 60 分钟，空气不好就通风",
                    "spec": spec,
                    "explanation": explanation,
                },
            )
            return raw[1] if isinstance(raw, tuple) else raw
        finally:
            MCP_TRACE_ID.reset(trace_token)
            MCP_INTERNAL.reset(internal_token)
            MCP_SCOPES.reset(scope_token)

    result = asyncio.run(invoke())
    assert result["ok"] is True
    assert result["data"]["status"] == "active"


def test_strategy_scheduler_creates_and_coalesces_significant_changes(client):
    seed_device()
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        policy = db.query(models.AutomationPolicy).filter_by(device_id="plan-device").one()
        policy.strategy_enabled = True
        db.commit()
    store = SqlAlchemyJobStore(SessionLocal, "strategy-test-worker")
    scheduler = PatrolScheduler(get_settings(), SessionLocal, store)
    assert scheduler.tick() == 1

    with SessionLocal() as db:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="plan-device",
                state={"window_open": True, "control_priority": "manual_first"},
                fusion={"air_quality": "alert"},
            ),
        )
    assert scheduler.tick() == 0
    with SessionLocal() as db:
        runs = db.query(models.AiRun).filter_by(device_id="plan-device", kind="strategy").all()
        assert len(runs) == 1
        assert runs[0].input_payload["coalesced_triggers"] == 1
