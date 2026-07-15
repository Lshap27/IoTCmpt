from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.job_store import RunCancelled, RunLeaseLost, SqlAlchemyJobStore
from app.adapters.mcp_client import McpToolClient
from app.core.config import Settings
from app.db import models
from app.domain.automation import evaluate_patrol
from app.generated.command_catalog import AI_COMMAND_NAMES
from app.services.analysis import collect_device_snapshot
from app.services.llm import LLMService
from app.services.plan_compiler import compile_mock_plan

LOGGER = logging.getLogger(__name__)
MAX_PLAN_REPAIR_ATTEMPTS = 3


class AiRunExecutionError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


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
        heartbeat = asyncio.create_task(
            self._renew_lease(run["run_id"], run["lease_token"]), name=f"lease-{run['run_id']}"
        )
        try:
            if run["kind"] == "report":
                output = await self._execute_report(run)
            elif run["kind"] == "plan_compile":
                output = await self._execute_plan_compile(run)
            elif run["kind"] == "strategy":
                output = await self._execute_strategy(run)
            else:
                output = await self._execute_tool_run(run)
            await asyncio.to_thread(
                self.store.complete,
                run["run_id"],
                output,
                str(output.get("model") or self.settings.llm_model),
                run["lease_token"],
            )
        except RunCancelled:
            LOGGER.info("AI run cancelled: %s", run["run_id"])
        except RunLeaseLost:
            LOGGER.warning("AI run lease lost; stale worker stopped: %s", run["run_id"])
        except Exception as exc:
            LOGGER.exception("AI run failed: %s", run["run_id"])
            await asyncio.to_thread(self.store.fail, run["run_id"], exc, run["lease_token"])
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _renew_lease(self, run_id: str, lease_token: str) -> None:
        while True:
            await asyncio.sleep(self.settings.ai_worker_heartbeat_seconds)
            renewed = await asyncio.to_thread(self.store.renew, run_id, lease_token)
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
            self._call_id(run, "report-history"),
            "device_get_history",
            {"device_id": run["device_id"], "limit": 2000, "start_at": start.isoformat()},
        )
        events = await self._call_tool(
            run,
            self._call_id(run, "report-events"),
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
            self._call_id(run, "snapshot"),
            "device_get_snapshot",
            {"device_id": run["device_id"]},
        )
        if not snapshot_result.get("ok"):
            raise RuntimeError(f"device snapshot unavailable: {snapshot_result.get('error')}")
        snapshot = snapshot_result.get("data") or {}
        if self.settings.llm_endpoint == "mock":
            return await self._execute_mock_tool_run(run, snapshot)
        return await self._execute_model_tool_loop(run)

    async def _execute_plan_compile(self, run: dict[str, Any]) -> dict[str, Any]:
        goal = str(run["input"].get("goal") or "").strip()
        if not goal:
            raise ValueError("plan_compile requires a non-empty goal")
        capabilities, snapshot, plans = await asyncio.gather(
            self._call_tool(
                run,
                self._call_id(run, "plan-capabilities"),
                "device_get_capabilities",
                {"device_id": run["device_id"]},
            ),
            self._call_tool(
                run,
                self._call_id(run, "plan-snapshot"),
                "device_get_snapshot",
                {"device_id": run["device_id"]},
            ),
            self._call_tool(
                run,
                self._call_id(run, "plan-current"),
                "automation_plan_list",
                {"device_id": run["device_id"]},
            ),
        )
        context: dict[str, Any] = {
            "capabilities": capabilities.get("data") if capabilities.get("ok") else None,
            "snapshot": snapshot.get("data") if snapshot.get("ok") else None,
            "plans": plans.get("data") if plans.get("ok") else [],
        }
        if self.settings.llm_endpoint == "mock":
            spec, explanation = compile_mock_plan(goal)
            result = await self._call_tool(
                run,
                self._call_id(run, "plan-create"),
                "automation_plan_create_draft",
                {
                    "device_id": run["device_id"],
                    "run_id": run["run_id"],
                    "source_prompt": goal,
                    "spec": spec,
                    "explanation": explanation,
                },
            )
            if not result.get("ok"):
                raise ValueError(f"plan validation failed: {result.get('error')}")
            plan = result.get("data") or {}
            return {
                "kind": "plan_compile",
                "model": "mock",
                "plan": plan,
                "auto_activated": plan.get("status") == "active",
                "blockers": plan.get("activation_blockers") or [],
            }
        return await self._execute_plan_model_call(run, goal, context)

    async def _execute_plan_model_call(
        self,
        run: dict[str, Any],
        goal: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        system = (
            "你是受限自动化计划编译器。必须且只能调用 automation_plan_create_draft 一次。"
            "只编译用户明确要求的动作，禁止补充关闭、复位、会话结束动作。"
            "DSL schema_version 必须为 1.0，manual_override_policy=respect，end_behavior=keep_state；"
            "只能使用工具 schema 允许的事实、触发器与动作。有歧义时写入 clarifications，不要自行猜测。"
            "时间语义必须严格区分：‘N 秒后’使用一次性 delay，‘每 N 秒’才使用 interval；两者最短 15 秒。"
            "中文‘提醒我’默认且必须使用 voice.speak；只有用户明确说在屏幕显示时才使用 display.message。"
            "例如‘半分钟后，提醒我“同学，学了这么久，该喝水啦”’应创建 duration_seconds=60、"
            "trigger={type:delay,after_seconds:30}、action={command:voice.speak,parameter:{},"
            "text:同学，学了这么久，该喝水啦} 的单规则计划。"
            "source_prompt 必须保留原始用户目标。"
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {"device_id": run["device_id"], "goal": goal, "context": context},
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
        async with self.mcp.session(run["trace_id"]) as session:
            listed = await session.list_tools()
            tools = self.mcp.openai_tools(
                listed.tools,
                allow_control=True,
                allowed_names={"automation_plan_create_draft"},
            )
            result, response_model = await self._call_required_tool_with_repairs(
                run,
                session,
                messages,
                tools,
                tool_name="automation_plan_create_draft",
                call_label="plan-create",
                argument_overrides={
                    "device_id": run["device_id"],
                    "run_id": run["run_id"],
                    "source_prompt": goal,
                },
            )
        plan = result.get("data") or {}
        return {
            "kind": "plan_compile",
            "model": response_model,
            "plan": plan,
            "auto_activated": plan.get("status") == "active",
            "blockers": plan.get("activation_blockers") or [],
        }

    async def _execute_strategy(self, run: dict[str, Any]) -> dict[str, Any]:
        plans_result = await self._call_tool(
            run,
            self._call_id(run, "strategy-plans"),
            "automation_plan_list",
            {"device_id": run["device_id"]},
        )
        if not plans_result.get("ok"):
            raise RuntimeError("strategy could not read automation plans")
        plans = plans_result.get("data") or []
        requested_plan_id = run["input"].get("plan_id")
        base = next(
            (
                plan
                for plan in plans
                if plan.get("plan_type") == "user"
                and (
                    plan.get("plan_id") == requested_plan_id
                    if requested_plan_id
                    else plan.get("status") in {"active", "paused"}
                )
            ),
            None,
        )
        snapshot_result = await self._call_tool(
            run,
            self._call_id(run, "strategy-snapshot"),
            "device_get_snapshot",
            {"device_id": run["device_id"]},
        )
        history_result = await self._call_tool(
            run,
            self._call_id(run, "strategy-history"),
            "device_get_history",
            {"device_id": run["device_id"], "limit": 288, "bucket_seconds": 300},
        )
        events_result: dict[str, Any] = {"ok": True, "data": []}
        if base:
            events_result = await self._call_tool(
                run,
                self._call_id(run, "strategy-events"),
                "automation_plan_events",
                {"device_id": run["device_id"], "plan_id": base["plan_id"], "limit": 200},
            )
        context: dict[str, Any] = {
            "snapshot": snapshot_result.get("data") if snapshot_result.get("ok") else None,
            "history": history_result.get("data") if history_result.get("ok") else None,
            "base_plan": base,
            "events": events_result.get("data") if events_result.get("ok") else [],
        }
        if self.settings.llm_endpoint == "mock":
            if base:
                proposed_spec = base["spec"]
                summary = "当前计划与设备状态一致，无需修改。"
            else:
                proposed_spec, _ = compile_mock_plan("持续 60 分钟，空气不好就通风")
                summary = "建议在空气质量告警时开窗通风；需用户批准后才会生效。"
            result = await self._propose_strategy(run, base, proposed_spec, summary)
        else:
            result = await self._execute_strategy_model_call(run, base, context)
        if not result.get("ok"):
            raise ValueError(f"strategy validation failed: {result.get('error')}")
        return {
            "kind": "strategy",
            "model": (
                "mock"
                if self.settings.llm_endpoint == "mock"
                else str(result.pop("_response_model", self.settings.llm_model))
            ),
            "strategy": result.get("data"),
        }

    async def _propose_strategy(
        self,
        run: dict[str, Any],
        base: dict[str, Any] | None,
        proposed_spec: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        return await self._call_tool(
            run,
            self._call_id(run, "strategy-propose"),
            "automation_strategy_propose",
            {
                "device_id": run["device_id"],
                "run_id": run["run_id"],
                "plan_id": base.get("plan_id") if base else None,
                "base_version": base.get("current_version") if base else None,
                "proposed_spec": proposed_spec,
                "summary": summary,
            },
        )

    async def _execute_strategy_model_call(
        self,
        run: dict[str, Any],
        base: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        system = (
            "你是 IoTCmpt 自动化策略复盘器。必须且只能调用 automation_strategy_propose 一次。"
            "只可产生待用户批准的 AutomationPlanSpec v1，不得激活计划或直接控制设备。"
            "保留用户意图，不新增用户未要求的反向动作或结束动作；无须修改时原样提交当前 spec。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]
        async with self.mcp.session(run["trace_id"]) as session:
            listed = await session.list_tools()
            tools = self.mcp.openai_tools(
                listed.tools,
                allow_control=True,
                allowed_names={"automation_strategy_propose"},
            )
            result, response_model = await self._call_required_tool_with_repairs(
                run,
                session,
                messages,
                tools,
                tool_name="automation_strategy_propose",
                call_label="strategy-propose",
                argument_overrides={
                    "device_id": run["device_id"],
                    "run_id": run["run_id"],
                    "plan_id": base.get("plan_id") if base else None,
                    "base_version": base.get("current_version") if base else None,
                },
            )
            return {**result, "_response_model": response_model}

    async def _call_required_tool_with_repairs(
        self,
        run: dict[str, Any],
        session: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_name: str,
        call_label: str,
        argument_overrides: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        last_error = "模型未返回有效工具调用"
        response_model = self.settings.llm_model
        for attempt in range(1, MAX_PLAN_REPAIR_ATTEMPTS + 1):
            await self._transition(run, "waiting_model")
            try:
                assistant = await self.llm.complete_with_tools(messages, tools, required_tool=tool_name)
            except Exception as exc:
                raise AiRunExecutionError(
                    "provider_tool_call_failed",
                    f"大模型工具调用失败：{type(exc).__name__}: {exc}",
                ) from exc
            response_model = str(assistant.get("_response_model") or response_model)
            calls = assistant.get("tool_calls") or []
            if len(calls) != 1:
                last_error = f"必须且只能调用 {tool_name} 一次，实际调用 {len(calls)} 次"
                self._append_repair_instruction(messages, last_error)
                continue
            call = calls[0]
            function = call.get("function") or {}
            if function.get("name") != tool_name:
                last_error = f"调用了不允许的工具：{function.get('name') or 'unknown'}"
                self._append_repair_instruction(messages, last_error)
                continue
            try:
                arguments = function.get("arguments") or "{}"
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise TypeError("工具参数必须是 JSON 对象")
            except (json.JSONDecodeError, TypeError) as exc:
                last_error = f"工具参数不是合法 JSON 对象：{exc}"
                self._append_repair_instruction(messages, last_error)
                continue
            arguments.update(argument_overrides)
            await self._transition(run, "calling_tool")
            call_id = self._call_id(run, f"{call_label}-{attempt}")
            try:
                result = await self._call_tool_with_session(
                    run,
                    session,
                    call_id,
                    tool_name,
                    arguments,
                )
            except Exception as exc:
                last_error = f"工具参数校验失败：{type(exc).__name__}: {exc}"
                result = {"ok": False, "error": last_error}
            if result.get("ok"):
                return result, response_model
            last_error = f"工具校验失败：{result.get('error') or 'unknown error'}"
            tool_call_id = str(call.get("id") or call_id)
            clean_assistant = {key: value for key, value in assistant.items() if not key.startswith("_")}
            messages.extend(
                [
                    clean_assistant,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps({"ok": False, "error": last_error[:1000]}, ensure_ascii=False),
                    },
                ]
            )
            self._append_repair_instruction(messages, last_error)
        raise AiRunExecutionError(
            "plan_repair_exhausted",
            f"AI 计划在 {MAX_PLAN_REPAIR_ATTEMPTS} 次修复后仍未通过校验：{last_error[:1200]}",
        )

    @staticmethod
    def _append_repair_instruction(messages: list[dict[str, Any]], error: str) -> None:
        messages.append(
            {
                "role": "user",
                "content": (
                    "上一次输出未通过受限计划校验。请仅修复下列错误，并重新调用同一个工具一次；"
                    f"不要输出解释文本：{error[:1000]}"
                ),
            }
        )

    async def _execute_mock_tool_run(self, run: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["analysis_intent"] = run["input"].get("goal") or run["kind"]
        snapshot["event_type"] = run["input"].get("latest_event_type") or run["input"].get("event_type")
        snapshot["run_kind"] = run["kind"]
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
        if run["kind"] not in {"decision", "patrol"}:
            if command is not None or decision.speech:
                output["policy"] = {"status": "read_only_run"}
            return output
        if command is not None and command.type not in AI_COMMAND_NAMES:
            output["policy"] = {"status": "denied", "command": command.type}
            return output
        if command is not None:
            arguments = {
                "device_id": run["device_id"],
                "command_type": command.type,
                "parameter": command.parameter,
                "reason": command.reason,
                "idempotency_key": f"{run['run_id']}:{self._call_id(run, 'mock-command')}",
            }
            await self._transition(run, "calling_tool")
            output["action"] = await self._call_tool(
                run,
                self._call_id(run, "mock-command"),
                "device_execute_command",
                arguments,
            )
        if decision.speech:
            await self._transition(run, "calling_tool")
            output["speech_action"] = await self._call_tool(
                run,
                self._call_id(run, "mock-speech"),
                "device_speak",
                {
                    "device_id": run["device_id"],
                    "text": decision.speech,
                    "reason": decision.summary,
                    "idempotency_key": f"{run['run_id']}:{self._call_id(run, 'mock-speech')}",
                },
            )
        return output

    async def _execute_model_tool_loop(self, run: dict[str, Any]) -> dict[str, Any]:
        system = (
            "你是 IoTCmpt 云端设备助手。必须通过提供的 MCP 工具读取设备状态；"
            "只有确有必要时才调用 device_execute_command 或 device_speak。固件本地安全规则拥有最终否决权。"
            "久坐事件可用 device_speak 提醒；巡检发现窗户已开但空气仍为 alert 且趋势恶化时可播报持续异常提醒；"
            "用户明确要求语音播报时可调用 device_speak。不得为烟雾或首次自动开窗通风追加云端播报。"
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
            await asyncio.to_thread(self.store.ensure_owned, run["run_id"], run["lease_token"])
            listed = await session.list_tools()
            allow_control = run["kind"] in {"decision", "patrol"}
            tools = self.mcp.openai_tools(listed.tools, allow_control=allow_control)
            for round_index in range(self.settings.ai_tool_max_rounds):
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
                for call_index, call in enumerate(calls):
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
                    model_call_id = str(call.get("id") or self._call_id(run, f"model-{round_index}-{call_index}"))
                    call_id = self._call_id(run, f"tool-{round_index}-{call_index}")
                    if name in {"device_execute_command", "device_speak"}:
                        if not allow_control:
                            raise PermissionError(f"{run['kind']} runs cannot control devices")
                        arguments["idempotency_key"] = f"{run['run_id']}:{call_id}"
                    await self._transition(run, "calling_tool")
                    result = await self._call_tool_with_session(run, session, call_id, name, arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": model_call_id,
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
            await asyncio.to_thread(self.store.ensure_owned, run["run_id"], run["lease_token"])
            raw = await session.call_tool(name, arguments)
            result = self.mcp.result_payload(raw)
        except Exception as exc:
            with contextlib.suppress(RunLeaseLost):
                await asyncio.to_thread(self.store.tool_finished, run, call_id, None, exc)
            raise
        if name in {"device_execute_command", "device_speak"} and result.get("ok"):
            result = await self._wait_for_command(run, session, result)
        await asyncio.to_thread(self.store.tool_finished, run, call_id, result, None)
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
            await asyncio.to_thread(self.store.ensure_owned, run["run_id"], run["lease_token"])
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
        await asyncio.to_thread(self.store.transition, run["run_id"], status, run["lease_token"])

    @staticmethod
    def _call_id(run: dict[str, Any], label: str) -> str:
        digest = hashlib.sha256(f"{run['run_id']}:{label}".encode()).hexdigest()[:24]
        return f"call-{digest}"


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
            strategy_policies = (
                db.query(models.AutomationPolicy)
                .filter(models.AutomationPolicy.enabled.is_(True), models.AutomationPolicy.strategy_enabled.is_(True))
                .all()
            )
            for policy in strategy_policies:
                fingerprint = self._strategy_fingerprint(db, policy.device_id)
                active = (
                    db.query(models.AiRun)
                    .filter(
                        models.AiRun.device_id == policy.device_id,
                        models.AiRun.kind == "strategy",
                        models.AiRun.status.in_(
                            ["queued", "running", "waiting_model", "calling_tool", "waiting_device"]
                        ),
                    )
                    .first()
                )
                if active is not None:
                    if fingerprint != (policy.last_strategy_fingerprint or {}):
                        active.input_payload = {
                            **(active.input_payload or {}),
                            "coalesced_triggers": int((active.input_payload or {}).get("coalesced_triggers", 0)) + 1,
                        }
                        policy.last_strategy_fingerprint = fingerprint
                        db.add_all([active, policy])
                    continue
                minimum_due = policy.last_strategy_run_at is None or now >= policy.last_strategy_run_at + timedelta(
                    seconds=policy.strategy_min_interval_seconds
                )
                force_due = policy.last_strategy_run_at is None or now >= policy.last_strategy_run_at + timedelta(
                    seconds=policy.strategy_force_interval_seconds
                )
                changed = fingerprint != (policy.last_strategy_fingerprint or {})
                if not minimum_due or (not changed and not force_due):
                    continue
                user_plan = (
                    db.query(models.AutomationPlan)
                    .filter(
                        models.AutomationPlan.device_id == policy.device_id,
                        models.AutomationPlan.plan_type == "user",
                        models.AutomationPlan.status.in_(["active", "paused"]),
                    )
                    .first()
                )
                db.add(
                    models.AiRun(
                        run_id=f"run-{uuid4().hex[:16]}",
                        trace_id=f"trace-{uuid4().hex[:16]}",
                        device_id=policy.device_id,
                        kind="strategy",
                        trigger="schedule",
                        status="queued",
                        available_at=now,
                        max_attempts=self.settings.ai_worker_max_attempts,
                        input_payload={
                            "kind": "strategy",
                            "trigger": "schedule",
                            "reason": "forced" if force_due and not changed else "significant_change",
                            "plan_id": user_plan.plan_id if user_plan else None,
                        },
                    )
                )
                policy.last_strategy_fingerprint = fingerprint
                db.add(policy)
                created += 1
            db.commit()
        return created

    @staticmethod
    def _strategy_fingerprint(db: Session, device_id: str) -> dict[str, Any]:
        snapshot = collect_device_snapshot(db, device_id)
        telemetry = snapshot.get("telemetry") or {}
        event = (
            db.query(models.AutomationPlanEvent)
            .filter(
                models.AutomationPlanEvent.device_id == device_id,
                models.AutomationPlanEvent.event_type.in_(
                    [
                        "command.executed",
                        "command.failed",
                        "command.rejected",
                        "command.expired",
                        "command.timed_out",
                        "blocked_by_manual_override",
                        "already_satisfied",
                    ]
                ),
            )
            .order_by(models.AutomationPlanEvent.occurred_at.desc())
            .first()
        )
        plan = (
            db.query(models.AutomationPlan)
            .filter(
                models.AutomationPlan.device_id == device_id,
                models.AutomationPlan.plan_type == "user",
                models.AutomationPlan.status.in_(["active", "paused"]),
            )
            .first()
        )
        return {
            "device_status": (snapshot.get("device") or {}).get("status"),
            "air_quality": (telemetry.get("fusion") or {}).get("air_quality"),
            "light_is_dark": (telemetry.get("sensors") or {}).get("light_is_dark"),
            "window_open": (telemetry.get("state") or {}).get("window_open"),
            "led_on": (telemetry.get("state") or {}).get("led_on"),
            "manual_window": (telemetry.get("state") or {}).get("manual_window_override"),
            "manual_led": (telemetry.get("state") or {}).get("manual_led_override"),
            "plan": [plan.plan_id, plan.current_version, plan.status] if plan else None,
            "event": [event.event_id, event.event_type] if event else None,
        }

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
