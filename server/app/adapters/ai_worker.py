from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.job_store import RunCancelled, SqlAlchemyJobStore
from app.adapters.mcp_client import McpToolClient
from app.core.config import Settings
from app.db import models
from app.domain.automation import evaluate_patrol
from app.generated.command_catalog import AI_COMMAND_NAMES
from app.services.analysis import collect_device_snapshot
from app.services.llm import LLMService

LOGGER = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AiRunWorker:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        llm: LLMService,
        mcp: McpToolClient,
        store: SqlAlchemyJobStore,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.llm = llm
        self.mcp = mcp
        self.store = store
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.settings.ai_worker_enabled and self._task is None:
            self._task = asyncio.create_task(self._run(), name="ai-run-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(
                    self.store.heartbeat_instance,
                    {"poll_seconds": self.settings.ai_worker_poll_seconds},
                )
                run = await asyncio.to_thread(self.store.claim_next)
                if run is None:
                    await asyncio.sleep(self.settings.ai_worker_poll_seconds)
                    continue
                await self.execute(run)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("AI worker loop failed")
                await asyncio.sleep(self.settings.ai_worker_poll_seconds)

    async def execute(self, run: dict[str, Any]) -> None:
        heartbeat = asyncio.create_task(self._renew_lease(run["run_id"]), name=f"lease-{run['run_id']}")
        try:
            if run["kind"] == "report":
                output = await self._execute_report(run)
            else:
                output = await self._execute_tool_run(run)
            await asyncio.to_thread(
                self.store.complete,
                run["run_id"],
                output,
                str(output.get("model") or self.settings.llm_model),
            )
        except RunCancelled:
            LOGGER.info("AI run cancelled: %s", run["run_id"])
        except Exception as exc:
            LOGGER.exception("AI run failed: %s", run["run_id"])
            await asyncio.to_thread(self.store.fail, run["run_id"], exc)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _renew_lease(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.ai_worker_heartbeat_seconds)
            renewed = await asyncio.to_thread(self.store.renew, run_id)
            await asyncio.to_thread(self.store.heartbeat_instance)
            if not renewed:
                return

    async def _execute_report(self, run: dict[str, Any]) -> dict[str, Any]:
        period = str(run["input"].get("period") or "day")
        durations = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(days=7)}
        if period not in durations:
            raise ValueError("unsupported report period")
        start = datetime.now(UTC) - durations[period]
        history = await self._call_tool(
            run,
            f"call-{uuid4().hex[:16]}",
            "device_get_history",
            {"device_id": run["device_id"], "limit": 2000, "start_at": start.isoformat()},
        )
        events = await self._call_tool(
            run,
            f"call-{uuid4().hex[:16]}",
            "device_list_events",
            {"device_id": run["device_id"], "limit": 500},
        )
        if not history.get("ok") or not events.get("ok"):
            raise RuntimeError("report MCP data collection failed")
        points = (history.get("data") or {}).get("points") or []
        context = self._report_context_from_tools(run["device_id"], period, points, events.get("data") or [])
        if context["coverage"]["sample_count"] == 0:
            raise ValueError("所选时段没有遥测数据")
        await self._transition(run, "waiting_model")
        result = await self.llm.generate_report(context)
        output = {
            "kind": "report",
            "device_id": run["device_id"],
            "period": period,
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "mock" if self.settings.llm_endpoint == "mock" else self.settings.llm_model,
            "coverage": context["coverage"],
            "metrics": context["metrics"],
            **result,
        }
        await asyncio.to_thread(self.store.persist_report, run, period, output)
        return output

    @staticmethod
    def _report_context_from_tools(
        device_id: str,
        period: str,
        points: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def values(name: str) -> list[float]:
            return [float(value) for point in points if (value := (point.get("sensors") or {}).get(name)) is not None]

        def average(name: str) -> float | None:
            rows = values(name)
            return sum(rows) / len(rows) if rows else None

        temperatures = values("temperature_c")
        eco2 = values("eco2_ppm")
        now = datetime.now(UTC)
        return {
            "device_id": device_id,
            "period": period,
            "coverage": {
                "start": min((str(point.get("sampled_at")) for point in points), default=now.isoformat()),
                "end": max((str(point.get("sampled_at")) for point in points), default=now.isoformat()),
                "sample_count": len(points),
                "bucket_count": len(points),
                "expected_bucket_count": len(points),
                "completeness_percent": 100.0 if points else 0.0,
            },
            "metrics": {
                "temperature_avg_c": average("temperature_c"),
                "temperature_min_c": min(temperatures) if temperatures else None,
                "temperature_max_c": max(temperatures) if temperatures else None,
                "humidity_avg_percent": average("humidity_percent"),
                "tvoc_avg_ppb": average("tvoc_ppb"),
                "hcho_avg_ug_m3": average("hcho_ug_m3"),
                "eco2_avg_ppm": average("eco2_ppm"),
                "eco2_max_ppm": max(eco2) if eco2 else None,
                "alert_bucket_count": sum(
                    (point.get("fusion") or {}).get("air_quality") == "alert" for point in points
                ),
                "smoke_event_count": sum(event.get("type") == "smoke.detected" for event in events),
            },
            "recent_points": points[:48],
        }

    async def _execute_tool_run(self, run: dict[str, Any]) -> dict[str, Any]:
        snapshot_result = await self._call_tool(
            run,
            f"call-{uuid4().hex[:16]}",
            "device_get_snapshot",
            {"device_id": run["device_id"]},
        )
        if not snapshot_result.get("ok"):
            raise RuntimeError(f"device snapshot unavailable: {snapshot_result.get('error')}")
        snapshot = snapshot_result.get("data") or {}
        if self.settings.llm_endpoint == "mock":
            return await self._execute_mock_tool_run(run, snapshot)
        return await self._execute_model_tool_loop(run)

    async def _execute_mock_tool_run(self, run: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["analysis_intent"] = run["input"].get("goal") or run["kind"]
        await self._transition(run, "waiting_model")
        decision = self.llm._mock_decision(snapshot)
        command = decision.command
        output: dict[str, Any] = {
            "kind": run["kind"],
            "summary": decision.summary,
            "risk_level": decision.risk_level,
            "model": "mock",
            "action": None,
        }
        if command is None:
            return output
        if command.type not in AI_COMMAND_NAMES:
            output["policy"] = {"status": "denied", "command": command.type}
            return output
        arguments = {
            "device_id": run["device_id"],
            "command_type": command.type,
            "parameter": command.parameter,
            "reason": command.reason,
            "idempotency_key": f"{run['run_id']}:{command.type}",
        }
        await self._transition(run, "calling_tool")
        result = await self._call_tool(run, f"call-{uuid4().hex[:16]}", "device_execute_command", arguments)
        output["action"] = result
        return output

    async def _execute_model_tool_loop(self, run: dict[str, Any]) -> dict[str, Any]:
        system = (
            "你是 IoTCmpt 云端设备助手。必须通过提供的 MCP 工具读取设备状态；"
            "只有确有必要时才调用 device_execute_command。固件本地安全规则拥有最终否决权。"
            "不要尝试关闭或静音报警，也不要修改控制优先级。最终用简体中文总结观察、工具执行结果和后续建议。"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "device_id": run["device_id"],
                        "run_kind": run["kind"],
                        "goal": run["input"].get("goal") or "检查设备状态并在必要时采取安全动作",
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        total_calls = 0
        async with self.mcp.session(run["trace_id"]) as session:
            listed = await session.list_tools()
            tools = self.mcp.openai_tools(listed.tools, allow_control=True)
            for _ in range(self.settings.ai_tool_max_rounds):
                await self._transition(run, "waiting_model")
                assistant = await self.llm.complete_with_tools(messages, tools)
                messages.append(assistant)
                calls = assistant.get("tool_calls") or []
                if not calls:
                    return {
                        "kind": run["kind"],
                        "summary": str(assistant.get("content") or "分析完成"),
                        "model": self.settings.llm_model,
                        "tool_call_count": total_calls,
                    }
                for call in calls:
                    total_calls += 1
                    if total_calls > self.settings.ai_tool_max_calls:
                        raise RuntimeError("AI tool call limit exceeded")
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    arguments = function.get("arguments") or "{}"
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be an object")
                    if name != "device_list":
                        arguments["device_id"] = run["device_id"]
                    call_id = str(call.get("id") or f"call-{uuid4().hex[:16]}")
                    await self._transition(run, "calling_tool")
                    result = await self._call_tool_with_session(run, session, call_id, name, arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
        raise RuntimeError("AI tool round limit exceeded")

    async def _call_tool(
        self,
        run: dict[str, Any],
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.mcp.session(run["trace_id"]) as session:
            return await self._call_tool_with_session(run, session, call_id, name, arguments)

    async def _call_tool_with_session(
        self,
        run: dict[str, Any],
        session: Any,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.store.tool_started, run, call_id, name, arguments)
        try:
            raw = await session.call_tool(name, arguments)
            result = self.mcp.result_payload(raw)
        except Exception as exc:
            await asyncio.to_thread(self.store.tool_finished, call_id, None, exc)
            raise
        if name == "device_execute_command" and result.get("ok"):
            result = await self._wait_for_command(run, session, result)
        await asyncio.to_thread(self.store.tool_finished, call_id, result, None)
        return result

    async def _wait_for_command(self, run: dict[str, Any], session: Any, result: dict[str, Any]) -> dict[str, Any]:
        command = result.get("data") or {}
        command_id = command.get("command_id")
        if not command_id:
            return result
        await self._transition(run, "waiting_device")
        deadline = asyncio.get_running_loop().time() + self.settings.command_ack_timeout_seconds
        terminal = {"executed", "rejected", "failed", "expired", "timed_out"}
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            raw = await session.call_tool(
                "device_get_command",
                {"device_id": run["device_id"], "command_id": command_id},
            )
            current = self.mcp.result_payload(raw)
            if current.get("ok") and (current.get("data") or {}).get("status") in terminal:
                return current
        return {
            "ok": True,
            "trace_id": run["trace_id"],
            "data": {**command, "status": "timed_out"},
            "error": None,
        }

    async def _transition(self, run: dict[str, Any], status: str) -> None:
        await asyncio.to_thread(self.store.transition, run["run_id"], status)


class PatrolScheduler:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        store: SqlAlchemyJobStore,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.store = store
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.settings.ai_worker_enabled and self._task is None:
            self._task = asyncio.create_task(self._run(), name="patrol-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("patrol scheduler failed")
            await asyncio.sleep(self.settings.patrol_scheduler_seconds)

    def tick(self) -> int:
        if not self.store.acquire_runtime_lease(
            "patrol-scheduler",
            max(10, int(self.settings.patrol_scheduler_seconds * 3)),
        ):
            return 0
        now = utcnow()
        created = 0
        with self.session_factory() as db:
            policies = (
                db.query(models.AutomationPolicy)
                .filter(models.AutomationPolicy.enabled.is_(True), models.AutomationPolicy.patrol_enabled.is_(True))
                .all()
            )
            for policy in policies:
                if policy.last_checked_at and now < policy.last_checked_at + timedelta(
                    seconds=policy.patrol_interval_seconds
                ):
                    continue
                active = (
                    db.query(models.AiRun)
                    .filter(
                        models.AiRun.device_id == policy.device_id,
                        models.AiRun.kind == "patrol",
                        models.AiRun.status.in_(
                            ["queued", "running", "waiting_model", "calling_tool", "waiting_device"]
                        ),
                    )
                    .first()
                )
                if active is not None:
                    active.input_payload = {
                        **(active.input_payload or {}),
                        "coalesced_triggers": int((active.input_payload or {}).get("coalesced_triggers", 0)) + 1,
                    }
                    policy.last_checked_at = now
                    db.add_all([active, policy])
                    continue
                snapshot = collect_device_snapshot(db, policy.device_id)
                decision = evaluate_patrol(
                    snapshot,
                    previous=policy.last_fingerprint,
                    last_model_run_at=policy.last_model_run_at,
                    force_interval_seconds=policy.patrol_force_interval_seconds,
                    now=now,
                    thresholds=policy.thresholds,
                )
                run = models.AiRun(
                    run_id=f"run-{uuid4().hex[:16]}",
                    trace_id=f"trace-{uuid4().hex[:16]}",
                    device_id=policy.device_id,
                    kind="patrol",
                    trigger="patrol",
                    status="queued" if decision.should_call_model else "skipped",
                    available_at=now,
                    max_attempts=self.settings.ai_worker_max_attempts,
                    input_payload={"kind": "patrol", "trigger": "patrol", "reason": decision.reason},
                    output_payload=None if decision.should_call_model else {"reason": "unchanged"},
                    completed_at=None if decision.should_call_model else now,
                )
                policy.last_fingerprint = decision.fingerprint
                policy.last_checked_at = now
                db.add_all([run, policy])
                created += 1
            db.commit()
        return created

    async def enqueue_event(self, device_id: str, event_type: str) -> None:
        if event_type not in {"smoke.detected", "air_quality.alert", "device.fault", "posture.sedentary"}:
            return
        await asyncio.to_thread(self._enqueue_event, device_id, event_type)

    def _enqueue_event(self, device_id: str, event_type: str) -> None:
        with self.session_factory() as db:
            policy = (
                db.query(models.AutomationPolicy).filter(models.AutomationPolicy.device_id == device_id).one_or_none()
            )
            if policy is None or not policy.enabled or not policy.event_trigger_enabled:
                return
            existing = (
                db.query(models.AiRun)
                .filter(
                    models.AiRun.device_id == device_id,
                    models.AiRun.trigger == "event",
                    models.AiRun.status.in_(["queued", "running", "waiting_model", "calling_tool", "waiting_device"]),
                )
                .first()
            )
            if existing is not None:
                return
            db.add(
                models.AiRun(
                    run_id=f"run-{uuid4().hex[:16]}",
                    trace_id=f"trace-{uuid4().hex[:16]}",
                    device_id=device_id,
                    kind="decision",
                    trigger="event",
                    status="queued",
                    available_at=utcnow(),
                    max_attempts=self.settings.ai_worker_max_attempts,
                    input_payload={"kind": "decision", "trigger": "event", "goal": f"处理事件 {event_type}"},
                )
            )
            db.commit()
