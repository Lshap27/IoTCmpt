from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import socket
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.automation_plans import SqlAlchemyAutomationPlanRepository
from app.application.commands import CommandApplicationService
from app.core.config import Settings
from app.db import models
from app.domain.automation_plans import plan_actuators
from app.domain.commands import CommandRejected, CommandRequest
from app.services.voice_commands import submit_speech

LOGGER = logging.getLogger(__name__)
POSE_MAX_AGE_SECONDS = 15
TERMINAL_COMMAND_STATUSES = {"executed", "rejected", "failed", "expired", "timed_out"}
SYSTEM_LIGHTING_SPEECH = "检测到环境光线较暗，已为您打开照明。"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _actuator(command: str) -> str:
    if command.startswith("window."):
        return "window"
    if command.startswith("led."):
        return "led"
    if command == "voice.speak":
        return "voice"
    if command == "display.message":
        return "display"
    return command


def _next_future(start: datetime, every_seconds: int, now: datetime) -> datetime:
    elapsed = max(0.0, (now - start).total_seconds())
    occurrence = math.floor(elapsed / every_seconds) + 1
    return start + timedelta(seconds=occurrence * every_seconds)


class AutomationRuntimeService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        commands: CommandApplicationService,
        plans: SqlAlchemyAutomationPlanRepository,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.commands = commands
        self.plans = plans
        self.instance_id = f"automation-{socket.gethostname()}-{uuid4().hex[:8]}"
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="automation-runtime")
            for device_id in await asyncio.to_thread(self._active_device_ids):
                await self.evaluate(device_id)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                if await asyncio.to_thread(self._acquire_scheduler_lease):
                    for device_id in await asyncio.to_thread(self._due_device_ids):
                        await self.evaluate(device_id, include_conditions=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("automation scheduler failed")
            await asyncio.sleep(self.settings.automation_scheduler_seconds)

    async def evaluate(self, device_id: str, *, include_conditions: bool = True) -> list[dict[str, Any]]:
        async with self._locks[device_id]:
            await asyncio.to_thread(self.plans.ensure_system_plan, device_id)
            candidates = await asyncio.to_thread(self._collect_candidates, device_id, include_conditions)
            results: list[dict[str, Any]] = []
            for candidate in candidates:
                result = await self._execute(candidate)
                if result is not None:
                    results.append(result)
            return results

    async def reconcile_command(self, device_id: str, command_id: str, status: str) -> dict[str, Any] | None:
        if status not in TERMINAL_COMMAND_STATUSES:
            return None
        async with self._locks[device_id]:
            state = await asyncio.to_thread(self._record_command_terminal, device_id, command_id, status)
            if state is None or status != "executed" or state["rule_id"] != "system-light-on":
                return None
            if state["speech_command_id"]:
                return None
            try:
                speech = await submit_speech(
                    self.commands,
                    device_id=device_id,
                    text=SYSTEM_LIGHTING_SPEECH,
                    source="rule",
                    reason="system lighting automation completed",
                    trace_id=state["trace_id"],
                    idempotency_key=f"automation-speech:{command_id}",
                    ai_restricted=True,
                )
            except CommandRejected as exc:
                await asyncio.to_thread(
                    self._append_event_by_plan,
                    state["plan_id"],
                    state["rule_id"],
                    "speech.blocked",
                    {"command_id": command_id, "error_code": exc.error_code},
                    state["trace_id"],
                )
                return None
            await asyncio.to_thread(self._save_speech_command, state["state_id"], speech["command_id"])
            return speech

    def _collect_candidates(self, device_id: str, include_conditions: bool) -> list[dict[str, Any]]:
        now = utcnow()
        with self.session_factory() as db:
            policy = db.query(models.AutomationPolicy).filter_by(device_id=device_id).one_or_none()
            if policy is not None and not policy.enabled:
                return []
            plans = (
                db.query(models.AutomationPlan)
                .filter(models.AutomationPlan.device_id == device_id, models.AutomationPlan.status == "active")
                .order_by(models.AutomationPlan.plan_type.desc())
                .all()
            )
            if not plans:
                return []
            for plan in plans:
                if plan.plan_type == "user" and plan.ends_at and plan.ends_at <= now:
                    plan.status = "completed"
                    plan.completed_at = now
                    self._event(db, plan, None, "plan.completed", {})
            db.flush()
            plans = [plan for plan in plans if plan.status == "active"]
            user_plan = next((plan for plan in plans if plan.plan_type == "user"), None)
            user_actuators: set[str] = set()
            if user_plan is not None:
                user_actuators = plan_actuators(self._spec(db, user_plan))
            facts, observation_key, telemetry = self._facts(db, device_id, now)
            candidates: list[dict[str, Any]] = []
            for plan in plans:
                spec = self._spec(db, plan)
                for rule in spec["rules"]:
                    command = rule["action"]["command"]
                    if plan.plan_type == "system" and _actuator(command) in user_actuators:
                        continue
                    state = (
                        db.query(models.AutomationRuleState)
                        .filter_by(
                            plan_id=plan.plan_id,
                            version=plan.current_version,
                            rule_id=rule["id"],
                        )
                        .one()
                    )
                    trigger = rule["trigger"]
                    occurrence_key: str | None = None
                    if trigger["type"] == "condition":
                        if not include_conditions:
                            continue
                        meta = dict(state.meta or {})
                        if meta.get("observation_key") == observation_key:
                            continue
                        meta["observation_key"] = observation_key
                        state.meta = meta
                        matched = self._condition(trigger, facts)
                        if plan.plan_type == "system" and state.last_condition == "unknown":
                            matched = self._system_condition_stable(db, device_id, trigger, facts)
                        if not matched:
                            state.stable_count = 0
                            state.last_condition = "false"
                            state.blocked_reason = None
                            continue
                        state.stable_count = (
                            trigger["stability_samples"]
                            if plan.plan_type == "system" and matched and state.last_condition == "unknown"
                            else state.stable_count + 1
                        )
                        if state.stable_count < trigger["stability_samples"]:
                            state.last_condition = "pending"
                            continue
                        if state.last_condition == "true":
                            current_block = self._manual_block(command, telemetry)
                            if current_block:
                                if state.blocked_reason != current_block:
                                    state.blocked_reason = current_block
                                    self._event(
                                        db,
                                        plan,
                                        rule["id"],
                                        "blocked_by_manual_override",
                                        {"actuator": current_block},
                                    )
                                continue
                            if not state.blocked_reason:
                                continue
                        state.last_condition = "true"
                        occurrence_key = observation_key
                    elif state.next_fire_at and state.next_fire_at <= now:
                        due = state.next_fire_at
                        state.next_fire_at = _next_future(plan.started_at or now, trigger["every_seconds"], now)
                        grace_seconds = max(5.0, self.settings.automation_scheduler_seconds * 2)
                        if (now - due).total_seconds() > grace_seconds:
                            self._event(
                                db,
                                plan,
                                rule["id"],
                                "interval.missed",
                                {"missed_at": due.isoformat(timespec="seconds")},
                            )
                            continue
                        occurrence_key = due.isoformat(timespec="seconds")
                    else:
                        continue
                    if state.last_fired_at and now < state.last_fired_at + timedelta(seconds=rule["cooldown_seconds"]):
                        self._event(db, plan, rule["id"], "rule.cooldown", {})
                        continue
                    blocked = self._manual_block(command, telemetry)
                    if blocked:
                        if state.blocked_reason != blocked:
                            state.blocked_reason = blocked
                            self._event(db, plan, rule["id"], "blocked_by_manual_override", {"actuator": blocked})
                        continue
                    state.blocked_reason = None
                    if self._already_satisfied(command, telemetry):
                        state.last_fired_at = now
                        self._event(db, plan, rule["id"], "already_satisfied", {"command": command})
                        continue
                    trace_id = f"trace-{uuid4().hex[:16]}"
                    occurrence = f"{plan.plan_id}:{plan.current_version}:{rule['id']}:{occurrence_key}"
                    state.last_occurrence_key = occurrence
                    candidates.append(
                        {
                            "plan_id": plan.plan_id,
                            "device_id": device_id,
                            "version": plan.current_version,
                            "rule_id": rule["id"],
                            "plan_type": plan.plan_type,
                            "action": rule["action"],
                            "reason": rule["description"],
                            "trace_id": trace_id,
                            "occurrence_key": occurrence,
                        }
                    )
            db.commit()
            return candidates

    async def _execute(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        action = candidate["action"]
        command = str(action["command"])
        try:
            if command == "voice.speak":
                result = await submit_speech(
                    self.commands,
                    device_id=candidate["device_id"],
                    text=str(action["text"]),
                    source="rule",
                    reason=candidate["reason"],
                    trace_id=candidate["trace_id"],
                    idempotency_key=candidate["occurrence_key"],
                    ai_restricted=True,
                )
            else:
                result = await self.commands.submit(
                    CommandRequest(
                        device_id=candidate["device_id"],
                        type=command,
                        parameter=dict(action.get("parameter") or {}),
                        source="rule",
                        reason=candidate["reason"],
                        trace_id=candidate["trace_id"],
                        idempotency_key=candidate["occurrence_key"],
                    ),
                    ai_restricted=True,
                )
        except CommandRejected as exc:
            await asyncio.to_thread(
                self._record_execution,
                candidate,
                None,
                "command.rejected",
                {"error_code": exc.error_code, "message": str(exc)},
            )
            return None
        await asyncio.to_thread(
            self._record_execution,
            candidate,
            result["command_id"],
            "command.submitted",
            {"command_id": result["command_id"], "command": command},
        )
        return result

    def _record_execution(
        self,
        candidate: dict[str, Any],
        command_id: str | None,
        event_type: str,
        detail: dict[str, Any],
    ) -> None:
        with self.session_factory() as db:
            plan = db.query(models.AutomationPlan).filter_by(plan_id=candidate["plan_id"]).one()
            state = (
                db.query(models.AutomationRuleState)
                .filter_by(
                    plan_id=plan.plan_id,
                    version=candidate["version"],
                    rule_id=candidate["rule_id"],
                )
                .one()
            )
            state.last_command_id = command_id
            state.last_fired_at = utcnow()
            state.last_occurrence_key = candidate["occurrence_key"]
            self._event(db, plan, candidate["rule_id"], event_type, detail, candidate["trace_id"])
            db.commit()

    def _record_command_terminal(self, device_id: str, command_id: str, status: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            state = (
                db.query(models.AutomationRuleState)
                .join(models.AutomationPlan, models.AutomationPlan.plan_id == models.AutomationRuleState.plan_id)
                .filter(
                    models.AutomationPlan.device_id == device_id,
                    models.AutomationRuleState.last_command_id == command_id,
                )
                .order_by(models.AutomationRuleState.updated_at.desc())
                .first()
            )
            if state is None:
                return None
            plan = db.query(models.AutomationPlan).filter_by(plan_id=state.plan_id).one()
            command = db.query(models.Command).filter_by(command_id=command_id).one_or_none()
            trace_id = command.trace_id if command else None
            self._event(db, plan, state.rule_id, f"command.{status}", {"command_id": command_id}, trace_id)
            speech_command_id = (state.meta or {}).get("speech_command_id")
            result = {
                "state_id": state.id,
                "plan_id": state.plan_id,
                "rule_id": state.rule_id,
                "trace_id": trace_id or f"trace-{uuid4().hex[:16]}",
                "speech_command_id": speech_command_id,
            }
            db.commit()
            return result

    def _save_speech_command(self, state_id: int, command_id: str) -> None:
        with self.session_factory() as db:
            state = db.get(models.AutomationRuleState, state_id)
            if state is not None:
                state.meta = {**(state.meta or {}), "speech_command_id": command_id}
                db.add(state)
                db.commit()

    def _append_event_by_plan(
        self,
        plan_id: str,
        rule_id: str | None,
        event_type: str,
        detail: dict[str, Any],
        trace_id: str | None,
    ) -> None:
        with self.session_factory() as db:
            plan = db.query(models.AutomationPlan).filter_by(plan_id=plan_id).one()
            self._event(db, plan, rule_id, event_type, detail, trace_id)
            db.commit()

    @staticmethod
    def _spec(db: Session, plan: models.AutomationPlan) -> dict[str, Any]:
        row = db.query(models.AutomationPlanVersion).filter_by(plan_id=plan.plan_id, version=plan.current_version).one()
        return row.spec

    @staticmethod
    def _facts(db: Session, device_id: str, now: datetime) -> tuple[dict[str, Any], str, models.Telemetry | None]:
        telemetry = (
            db.query(models.Telemetry)
            .filter(models.Telemetry.device_id == device_id)
            .order_by(models.Telemetry.sampled_at.desc(), models.Telemetry.id.desc())
            .first()
        )
        pose = (
            db.query(models.PoseResult)
            .filter(models.PoseResult.device_id == device_id)
            .order_by(models.PoseResult.created_at.desc(), models.PoseResult.id.desc())
            .first()
        )
        device = db.query(models.Device).filter_by(device_id=device_id).one_or_none()
        pose_fresh = bool(pose and pose.created_at and pose.created_at >= now - timedelta(seconds=POSE_MAX_AGE_SECONDS))
        facts = {
            "light_is_dark": telemetry.light_is_dark if telemetry else None,
            "human_present": pose.human_present if pose_fresh and pose else None,
            "air_quality": telemetry.air_quality if telemetry else None,
            "temperature_c": telemetry.temperature_c if telemetry else None,
            "humidity_percent": telemetry.humidity_percent if telemetry else None,
            "tvoc_ppb": telemetry.tvoc_ppb if telemetry else None,
            "hcho_ug_m3": telemetry.hcho_ug_m3 if telemetry else None,
            "eco2_ppm": telemetry.eco2_ppm if telemetry else None,
            "window_open": telemetry.window_open if telemetry else None,
            "led_on": telemetry.led_on if telemetry else None,
            "device_status": device.status if device else "unknown",
        }
        telemetry_key = telemetry.id if telemetry else "none"
        pose_key = pose.id if pose_fresh and pose else "none"
        observation_key = f"telemetry:{telemetry_key}:pose:{pose_key}:device:{device.status if device else 'unknown'}"
        return facts, observation_key, telemetry

    @staticmethod
    def _condition(trigger: dict[str, Any], facts: dict[str, Any]) -> bool:
        values: list[bool] = []
        for item in trigger["items"]:
            actual = facts.get(item["fact"])
            expected = item["value"]
            op = item["op"]
            if actual is None:
                values.append(False)
            elif op == "eq":
                values.append(actual == expected)
            elif op == "in":
                values.append(actual in expected)
            elif op == "gt":
                values.append(float(actual) > float(expected))
            elif op == "gte":
                values.append(float(actual) >= float(expected))
            elif op == "lt":
                values.append(float(actual) < float(expected))
            elif op == "lte":
                values.append(float(actual) <= float(expected))
        return all(values) if trigger["mode"] == "all" else any(values)

    def _system_condition_stable(
        self,
        db: Session,
        device_id: str,
        trigger: dict[str, Any],
        current_facts: dict[str, Any],
    ) -> bool:
        required = int(trigger["stability_samples"])
        samples = (
            db.query(models.Telemetry)
            .filter(models.Telemetry.device_id == device_id)
            .order_by(models.Telemetry.sampled_at.desc(), models.Telemetry.id.desc())
            .limit(required)
            .all()
        )
        if len(samples) < required:
            return False
        for sample in samples:
            facts = {
                **current_facts,
                "light_is_dark": sample.light_is_dark,
                "air_quality": sample.air_quality,
                "temperature_c": sample.temperature_c,
                "humidity_percent": sample.humidity_percent,
                "tvoc_ppb": sample.tvoc_ppb,
                "hcho_ug_m3": sample.hcho_ug_m3,
                "eco2_ppm": sample.eco2_ppm,
                "window_open": sample.window_open,
                "led_on": sample.led_on,
            }
            if not self._condition(trigger, facts):
                return False
        return True

    @staticmethod
    def _manual_block(command: str, telemetry: models.Telemetry | None) -> str | None:
        if telemetry is None or telemetry.control_priority != "manual_first":
            return None
        if command.startswith("window.") and telemetry.manual_window_override:
            return "window"
        if command.startswith("led.") and telemetry.manual_led_override:
            return "led"
        return None

    @staticmethod
    def _already_satisfied(command: str, telemetry: models.Telemetry | None) -> bool:
        if telemetry is None:
            return False
        return (
            (command == "window.open" and telemetry.window_open is True)
            or (command == "window.close" and telemetry.window_open is False)
            or (command == "led.on" and telemetry.led_on is True)
            or (command == "led.off" and telemetry.led_on is False)
        )

    def _active_device_ids(self) -> list[str]:
        with self.session_factory() as db:
            return [
                row[0]
                for row in db.query(models.AutomationPlan.device_id)
                .filter(models.AutomationPlan.status == "active")
                .distinct()
            ]

    def _due_device_ids(self) -> list[str]:
        now = utcnow()
        with self.session_factory() as db:
            rows = (
                db.query(models.AutomationPlan.device_id)
                .join(models.AutomationRuleState, models.AutomationRuleState.plan_id == models.AutomationPlan.plan_id)
                .filter(
                    models.AutomationPlan.status == "active",
                    (models.AutomationRuleState.next_fire_at <= now)
                    | ((models.AutomationPlan.ends_at.is_not(None)) & (models.AutomationPlan.ends_at <= now)),
                )
                .distinct()
                .all()
            )
            return [row[0] for row in rows]

    def _acquire_scheduler_lease(self) -> bool:
        now = utcnow()
        seconds = max(2, int(self.settings.automation_scheduler_seconds * 3))
        with self.session_factory() as db:
            query = db.query(models.RuntimeLease).filter_by(name="automation-scheduler")
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update()
            lease = query.one_or_none()
            if lease and lease.owner != self.instance_id and lease.lease_expires_at > now:
                return False
            if lease is None:
                lease = models.RuntimeLease(name="automation-scheduler", owner=self.instance_id, lease_expires_at=now)
            lease.owner = self.instance_id
            lease.heartbeat_at = now
            lease.lease_expires_at = now + timedelta(seconds=seconds)
            db.add(lease)
            db.commit()
            return True

    @staticmethod
    def _event(
        db: Session,
        plan: models.AutomationPlan,
        rule_id: str | None,
        event_type: str,
        detail: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        plan_event_id = f"plan-event-{uuid4().hex[:20]}"
        payload = {
            "event_id": plan_event_id,
            "plan_id": plan.plan_id,
            "version": plan.current_version,
            "rule_id": rule_id,
            "event_type": event_type,
            "detail": detail,
        }
        db.add(
            models.AutomationPlanEvent(
                event_id=plan_event_id,
                plan_id=plan.plan_id,
                device_id=plan.device_id,
                version=plan.current_version,
                rule_id=rule_id,
                trace_id=trace_id,
                event_type=event_type,
                detail=detail,
            )
        )
        db.add(
            models.RealtimeEvent(
                event_id=f"evt-{uuid4().hex[:20]}",
                device_id=plan.device_id,
                trace_id=trace_id,
                type="automation.plan.event",
                payload=payload,
            )
        )
        if event_type.startswith("plan."):
            db.add(
                models.RealtimeEvent(
                    event_id=f"evt-{uuid4().hex[:20]}",
                    device_id=plan.device_id,
                    trace_id=trace_id,
                    type="automation.plan.changed",
                    payload={
                        "plan_id": plan.plan_id,
                        "status": plan.status,
                        "current_version": plan.current_version,
                    },
                )
            )


class LightingAutomationCompatibilityFacade:
    """Preserve the former app-state call shape without restoring its execution path."""

    def __init__(self, runtime: AutomationRuntimeService, session_factory: sessionmaker[Session]) -> None:
        self.runtime = runtime
        self.session_factory = session_factory

    async def evaluate(self, device_id: str) -> dict[str, Any] | None:
        rows = await self.runtime.evaluate(device_id)
        return rows[0] if rows else None

    async def reconcile_command(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        status = await asyncio.to_thread(self._command_status, device_id, command_id)
        return await self.runtime.reconcile_command(device_id, command_id, status)

    def _command_status(self, device_id: str, command_id: str) -> str:
        with self.session_factory() as db:
            command = db.query(models.Command).filter_by(device_id=device_id, command_id=command_id).one_or_none()
            return command.status if command else "unknown"
