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
from app.domain.commands import CommandRejected, CommandRequest
from app.services.voice_commands import submit_speech

LOGGER = logging.getLogger(__name__)
POSE_MAX_AGE_SECONDS = 15
TERMINAL_COMMAND_STATUSES = {"executed", "rejected", "failed", "expired", "timed_out"}
SYSTEM_ANNOUNCEMENTS = {
    "system-light-on": "检测到环境光线较暗，已为您打开照明。",
    "system-air-open": "检测到空气质量异常，已为您开窗通风。",
}


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


def _stateful_actuator(command: str) -> str | None:
    actuator = _actuator(command)
    return actuator if actuator in {"window", "led"} else None


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
            await asyncio.to_thread(self._clear_stale_claims)
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
            if state is None or status != "executed" or not state.get("announcement"):
                return None
            if state["speech_command_id"]:
                return None
            try:
                speech = await submit_speech(
                    self.commands,
                    device_id=device_id,
                    text=str(state["announcement"]),
                    source="rule",
                    reason="system automation action completed",
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

    def _clear_stale_claims(self) -> None:
        with self.session_factory() as db:
            db.query(models.AutomationActuatorClaim).delete(synchronize_session=False)
            db.commit()

    def _collect_candidates(self, device_id: str, include_conditions: bool) -> list[dict[str, Any]]:
        now = utcnow()
        with self.session_factory() as db:
            policy = db.query(models.AutomationPolicy).filter_by(device_id=device_id).one_or_none()
            if policy is not None and not policy.enabled:
                db.query(models.AutomationActuatorClaim).filter_by(device_id=device_id).delete(
                    synchronize_session=False
                )
                db.commit()
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
                    db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(
                        synchronize_session=False
                    )
                    self._event(db, plan, None, "plan.completed", {})
            db.flush()
            plans = [plan for plan in plans if plan.status == "active"]
            facts, observation_key, telemetry = self._facts(db, device_id, now)
            direct_candidates: list[dict[str, Any]] = []
            stateful_matches: list[dict[str, Any]] = []
            for plan in plans:
                spec = self._spec(db, plan)
                for rule in spec["rules"]:
                    command = rule["action"]["command"]
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
                    became_true = False
                    if trigger["type"] == "condition":
                        if not include_conditions:
                            continue
                        meta = dict(state.meta or {})
                        new_observation = meta.get("observation_key") != observation_key
                        if new_observation:
                            meta["observation_key"] = observation_key
                            control_reset_key = ":".join(
                                (
                                    str(facts.get("device_status")),
                                    str(telemetry.manual_window_override if telemetry else None),
                                    str(telemetry.manual_led_override if telemetry else None),
                                )
                            )
                            if meta.get("control_reset_key") not in {None, control_reset_key}:
                                for key in ("retry_count", "retry_after", "retry_exhausted"):
                                    meta.pop(key, None)
                            meta["control_reset_key"] = control_reset_key
                            state.meta = meta
                        matched = self._condition(trigger, facts)
                        if plan.plan_type == "system" and state.last_condition == "unknown":
                            matched = self._system_condition_stable(db, device_id, trigger, facts)
                        if not matched:
                            if new_observation:
                                state.stable_count = 0
                                state.last_condition = "false"
                                state.blocked_reason = None
                                state.meta = {
                                    key: value
                                    for key, value in (state.meta or {}).items()
                                    if key not in {"retry_count", "retry_after", "retry_exhausted"}
                                }
                            continue
                        previous_condition = state.last_condition
                        if new_observation:
                            state.stable_count = (
                                trigger["stability_samples"]
                                if plan.plan_type == "system" and previous_condition == "unknown"
                                else state.stable_count + 1
                            )
                        if state.stable_count < trigger["stability_samples"]:
                            state.last_condition = "pending"
                            continue
                        became_true = previous_condition != "true"
                        state.last_condition = "true"
                        occurrence_key = observation_key
                    elif state.next_fire_at and state.next_fire_at <= now:
                        due = state.next_fire_at
                        grace_seconds = max(5.0, self.settings.automation_scheduler_seconds * 2)
                        if trigger["type"] == "interval":
                            state.next_fire_at = _next_future(plan.started_at or now, trigger["every_seconds"], now)
                            missed_event = "interval.missed"
                        else:
                            state.next_fire_at = None
                            missed_event = "delay.missed"
                        if (now - due).total_seconds() > grace_seconds:
                            if trigger["type"] == "delay":
                                state.meta = {**(state.meta or {}), "delay_status": "missed"}
                            self._event(
                                db,
                                plan,
                                rule["id"],
                                missed_event,
                                {"missed_at": due.isoformat(timespec="seconds")},
                            )
                            if trigger["type"] == "delay":
                                self._finish_delay_only_plan(db, plan, succeeded=False, detail={"reason": "missed"})
                            continue
                        occurrence_key = due.isoformat(timespec="seconds")
                        became_true = True
                        if trigger["type"] == "delay":
                            state.meta = {**(state.meta or {}), "delay_status": "firing"}
                            self._event(
                                db,
                                plan,
                                rule["id"],
                                "delay.fired",
                                {"scheduled_at": due.isoformat(timespec="seconds")},
                            )
                    else:
                        continue
                    entry = {
                        "plan": plan,
                        "state": state,
                        "rule": rule,
                        "command": command,
                        "actuator": _stateful_actuator(command),
                        "occurrence_key": occurrence_key,
                        "became_true": became_true,
                    }
                    if entry["actuator"]:
                        stateful_matches.append(entry)
                    elif became_true:
                        candidate = self._candidate_from_entries(device_id, [entry], occurrence_key or observation_key)
                        if self._candidate_ready(db, candidate, telemetry, now):
                            direct_candidates.append(candidate)

            desired_claims: dict[str, dict[str, Any]] = {}
            stateful_candidates: list[dict[str, Any]] = []
            for actuator in ("window", "led"):
                user_entries = [
                    entry
                    for entry in stateful_matches
                    if entry["actuator"] == actuator and entry["plan"].plan_type == "user"
                ]
                system_entries = [
                    entry
                    for entry in stateful_matches
                    if entry["actuator"] == actuator and entry["plan"].plan_type == "system"
                ]
                winning = user_entries or system_entries
                suppressed = system_entries if user_entries else []
                for entry in suppressed:
                    state = entry["state"]
                    if state.blocked_reason != "suppressed_by_user_plan":
                        state.blocked_reason = "suppressed_by_user_plan"
                        self._event(
                            db,
                            entry["plan"],
                            entry["rule"]["id"],
                            "rule.suppressed",
                            {"actuator": actuator, "reason": "suppressed_by_user_plan"},
                        )
                if not winning:
                    continue
                commands = {str(entry["command"]) for entry in winning}
                owner = winning[0]["plan"]
                rule_ids = sorted({str(entry["rule"]["id"]) for entry in winning})
                occurrence = ":".join(sorted(str(entry["occurrence_key"]) for entry in winning))
                if len(commands) > 1:
                    desired_claims[actuator] = {
                        "plan": owner,
                        "rule_ids": rule_ids,
                        "target_command": None,
                        "status": "conflict",
                        "reason": "opposite rules matched at the same priority",
                        "observation_key": occurrence,
                    }
                    for entry in winning:
                        state = entry["state"]
                        if state.blocked_reason != f"conflict:{actuator}":
                            state.blocked_reason = f"conflict:{actuator}"
                            self._event(
                                db,
                                entry["plan"],
                                entry["rule"]["id"],
                                "rule.conflict",
                                {"actuator": actuator, "commands": sorted(commands)},
                            )
                    continue
                command = next(iter(commands))
                desired_claims[actuator] = {
                    "plan": owner,
                    "rule_ids": rule_ids,
                    "target_command": command,
                    "status": "claimed",
                    "reason": "; ".join(str(entry["rule"]["description"]) for entry in winning),
                    "observation_key": occurrence,
                }
                for entry in winning:
                    if entry["state"].blocked_reason in {
                        "suppressed_by_user_plan",
                        f"conflict:{actuator}",
                    }:
                        entry["state"].blocked_reason = None
                candidate = self._candidate_from_entries(device_id, winning, occurrence)
                if self._candidate_ready(db, candidate, telemetry, now):
                    stateful_candidates.append(candidate)

            self._retain_timed_claims(db, plans, desired_claims, telemetry)
            self._sync_claims(db, device_id, desired_claims)
            db.commit()
            return [*stateful_candidates, *direct_candidates]

    def _retain_timed_claims(
        self,
        db: Session,
        plans: list[models.AutomationPlan],
        desired: dict[str, dict[str, Any]],
        telemetry: models.Telemetry | None,
    ) -> None:
        for plan in plans:
            if plan.plan_type != "user":
                continue
            spec = self._spec(db, plan)
            rules = {rule["id"]: rule for rule in spec["rules"]}
            states = db.query(models.AutomationRuleState).filter_by(plan_id=plan.plan_id, version=plan.current_version)
            pending: dict[tuple[str, str], list[models.AutomationRuleState]] = defaultdict(list)
            for state in states:
                rule = rules[state.rule_id]
                actuator = _stateful_actuator(str(rule["action"]["command"]))
                if rule["trigger"]["type"] not in {"interval", "delay"} or not actuator or actuator in desired:
                    continue
                if not state.last_command_id:
                    continue
                command = db.query(models.Command).filter_by(command_id=state.last_command_id).one_or_none()
                if command is None:
                    continue
                awaiting_terminal = command.status not in TERMINAL_COMMAND_STATUSES
                awaiting_state = bool(
                    command.status == "executed"
                    and command.executed_at
                    and (telemetry is None or telemetry.sampled_at <= command.executed_at)
                )
                if awaiting_terminal or awaiting_state:
                    pending[(actuator, command.type)].append(state)
            for (actuator, command_type), grouped_states in pending.items():
                rule_ids = sorted(state.rule_id for state in grouped_states)
                desired[actuator] = {
                    "plan": plan,
                    "rule_ids": rule_ids,
                    "target_command": command_type,
                    "status": "claimed",
                    "reason": "timed action awaiting terminal ACK or a newer device state",
                    "observation_key": ":".join(
                        str(state.last_occurrence_key or state.last_command_id) for state in grouped_states
                    ),
                }

    def _candidate_from_entries(
        self, device_id: str, entries: list[dict[str, Any]], occurrence_key: str
    ) -> dict[str, Any]:
        first = entries[0]
        plan = first["plan"]
        rule_ids = sorted({str(entry["rule"]["id"]) for entry in entries})
        return {
            "plan_id": plan.plan_id,
            "device_id": device_id,
            "version": plan.current_version,
            "rule_id": rule_ids[0],
            "rule_ids": rule_ids,
            "plan_type": plan.plan_type,
            "action": first["rule"]["action"],
            "reason": "; ".join(str(entry["rule"]["description"]) for entry in entries),
            "trace_id": f"trace-{uuid4().hex[:16]}",
            "occurrence_key": (f"{plan.plan_id}:{plan.current_version}:{','.join(rule_ids)}:{occurrence_key}"),
            "states": [entry["state"] for entry in entries],
        }

    def _candidate_ready(
        self,
        db: Session,
        candidate: dict[str, Any],
        telemetry: models.Telemetry | None,
        now: datetime,
    ) -> bool:
        command = str(candidate["action"]["command"])
        states: list[models.AutomationRuleState] = candidate["states"]
        blocked = self._manual_block(command, telemetry)
        if blocked:
            plan = db.query(models.AutomationPlan).filter_by(plan_id=candidate["plan_id"]).one()
            for state in states:
                if state.blocked_reason != blocked:
                    state.blocked_reason = blocked
                    self._event(db, plan, state.rule_id, "blocked_by_manual_override", {"actuator": blocked})
            return False
        retry_counts = [int((state.meta or {}).get("retry_count") or 0) for state in states]
        cooldown = max(
            int(self._rule_by_id(db, candidate["plan_id"], candidate["version"], state.rule_id)["cooldown_seconds"])
            for state in states
        )
        if not any(retry_counts) and any(
            state.last_fired_at and now < state.last_fired_at + timedelta(seconds=cooldown) for state in states
        ):
            return False
        if self._already_satisfied(command, telemetry):
            plan = db.query(models.AutomationPlan).filter_by(plan_id=candidate["plan_id"]).one()
            for state in states:
                if state.blocked_reason != "already_satisfied":
                    self._event(
                        db,
                        plan,
                        state.rule_id,
                        "already_satisfied",
                        {"command": command},
                    )
                state.blocked_reason = "already_satisfied"
            return False
        for state in states:
            if state.last_command_id:
                command_row = db.query(models.Command).filter_by(command_id=state.last_command_id).one_or_none()
                if command_row and command_row.status not in TERMINAL_COMMAND_STATUSES:
                    return False
            meta = dict(state.meta or {})
            retry_count = int(meta.get("retry_count") or 0)
            retry_after = meta.get("retry_after")
            if retry_count > 3:
                if not meta.get("retry_exhausted"):
                    plan = db.query(models.AutomationPlan).filter_by(plan_id=candidate["plan_id"]).one()
                    self._event(
                        db,
                        plan,
                        state.rule_id,
                        "command.retry_exhausted",
                        {"attempts": retry_count},
                    )
                    meta["retry_exhausted"] = True
                    state.meta = meta
                return False
            if retry_after and datetime.fromisoformat(str(retry_after)) > now:
                return False
            state.blocked_reason = None
        if any(retry_counts):
            candidate["occurrence_key"] = f"{candidate['occurrence_key']}:retry:{max(retry_counts)}"
        return True

    def _rule_by_id(self, db: Session, plan_id: str, version: int, rule_id: str) -> dict[str, Any]:
        row = db.query(models.AutomationPlanVersion).filter_by(plan_id=plan_id, version=version).one()
        return next(rule for rule in row.spec["rules"] if rule["id"] == rule_id)

    def _sync_claims(self, db: Session, device_id: str, desired: dict[str, dict[str, Any]]) -> None:
        existing = {
            row.actuator: row for row in db.query(models.AutomationActuatorClaim).filter_by(device_id=device_id).all()
        }
        for actuator, row in existing.items():
            if actuator in desired:
                continue
            previous_plan = db.query(models.AutomationPlan).filter_by(plan_id=row.plan_id).one_or_none()
            if previous_plan is not None:
                self._event(
                    db,
                    previous_plan,
                    row.rule_ids[0] if row.rule_ids else None,
                    "rule.released",
                    {"actuator": actuator, "target_command": row.target_command},
                )
            db.delete(row)
        for actuator, value in desired.items():
            current_plan: models.AutomationPlan = value["plan"]
            claim = existing.get(actuator)
            changed = claim is None or any(
                (
                    claim.plan_id != current_plan.plan_id,
                    claim.version != current_plan.current_version,
                    set(claim.rule_ids or []) != set(value["rule_ids"]),
                    claim.target_command != value["target_command"],
                    claim.status != value["status"],
                )
            )
            if claim is None:
                claim = models.AutomationActuatorClaim(device_id=device_id, actuator=actuator)
            claim.owner_type = current_plan.plan_type
            claim.plan_id = current_plan.plan_id
            claim.version = current_plan.current_version
            claim.rule_ids = value["rule_ids"]
            claim.target_command = value["target_command"]
            claim.status = value["status"]
            claim.reason = value["reason"][:160]
            claim.observation_key = value["observation_key"][:200]
            db.add(claim)
            if changed and value["status"] != "conflict":
                self._event(
                    db,
                    current_plan,
                    value["rule_ids"][0],
                    "rule.claimed",
                    {
                        "actuator": actuator,
                        "rule_ids": value["rule_ids"],
                        "target_command": value["target_command"],
                    },
                )

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
                        automation_plan_id=candidate["plan_id"],
                        automation_plan_version=candidate["version"],
                        automation_rule_ids=tuple(candidate["rule_ids"]),
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
            states = (
                db.query(models.AutomationRuleState)
                .filter(
                    models.AutomationRuleState.plan_id == plan.plan_id,
                    models.AutomationRuleState.version == candidate["version"],
                    models.AutomationRuleState.rule_id.in_(candidate["rule_ids"]),
                )
                .all()
            )
            for state in states:
                state.last_command_id = command_id
                state.last_fired_at = utcnow()
                state.last_occurrence_key = candidate["occurrence_key"]
                rule = self._rule_by_id(db, plan.plan_id, candidate["version"], state.rule_id)
                if command_id is None and rule["trigger"]["type"] == "condition":
                    self._schedule_retry(db, plan, state, detail)
                elif rule["trigger"]["type"] == "delay":
                    state.meta = {
                        **(state.meta or {}),
                        "delay_status": "submitted" if command_id else "failed",
                    }
                self._event(db, plan, state.rule_id, event_type, detail, candidate["trace_id"])
            if command_id:
                actuator = _stateful_actuator(str(candidate["action"]["command"]))
                claim = (
                    db.query(models.AutomationActuatorClaim)
                    .filter_by(device_id=plan.device_id, plan_id=plan.plan_id, actuator=actuator)
                    .one_or_none()
                    if actuator
                    else None
                )
                if claim is not None and set(claim.rule_ids or []) == set(candidate["rule_ids"]):
                    claim.command_id = command_id
            if command_id is None:
                self._finish_delay_only_plan(db, plan, succeeded=False, detail=detail)
            db.commit()

    def _record_command_terminal(self, device_id: str, command_id: str, status: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            states = (
                db.query(models.AutomationRuleState)
                .join(models.AutomationPlan, models.AutomationPlan.plan_id == models.AutomationRuleState.plan_id)
                .filter(
                    models.AutomationPlan.device_id == device_id,
                    models.AutomationRuleState.last_command_id == command_id,
                )
                .order_by(models.AutomationRuleState.updated_at.desc())
                .all()
            )
            if not states:
                return None
            state = states[0]
            plan = db.query(models.AutomationPlan).filter_by(plan_id=state.plan_id).one()
            command = db.query(models.Command).filter_by(command_id=command_id).one_or_none()
            trace_id = command.trace_id if command else None
            announcement = None
            speech_command_id = None
            for item in states:
                meta = dict(item.meta or {})
                if status == "executed":
                    for key in ("retry_count", "retry_after", "retry_exhausted"):
                        meta.pop(key, None)
                    item.meta = meta
                    item.blocked_reason = None
                else:
                    rule = self._rule_by_id(db, plan.plan_id, plan.current_version, item.rule_id)
                    if rule["trigger"]["type"] == "condition":
                        self._schedule_retry(db, plan, item, {"status": status, "command_id": command_id})
                rule = self._rule_by_id(db, plan.plan_id, plan.current_version, item.rule_id)
                if rule["trigger"]["type"] == "delay":
                    meta = dict(item.meta or {})
                    meta["delay_status"] = "executed" if status == "executed" else "failed"
                    item.meta = meta
                    if status == "executed":
                        self._event(
                            db,
                            plan,
                            item.rule_id,
                            "delay.completed",
                            {"command_id": command_id},
                            trace_id,
                        )
                self._event(db, plan, item.rule_id, f"command.{status}", {"command_id": command_id}, trace_id)
                if item.rule_id in SYSTEM_ANNOUNCEMENTS and announcement is None:
                    announcement = SYSTEM_ANNOUNCEMENTS[item.rule_id]
                    speech_command_id = meta.get("speech_command_id")
            self._finish_delay_only_plan(
                db,
                plan,
                succeeded=status == "executed",
                detail={"status": status, "command_id": command_id},
            )
            result = {
                "state_id": state.id,
                "plan_id": state.plan_id,
                "rule_id": state.rule_id,
                "rule_ids": [item.rule_id for item in states],
                "trace_id": trace_id or f"trace-{uuid4().hex[:16]}",
                "speech_command_id": speech_command_id,
                "announcement": announcement,
            }
            db.commit()
            return result

    def _finish_delay_only_plan(
        self,
        db: Session,
        plan: models.AutomationPlan,
        *,
        succeeded: bool,
        detail: dict[str, Any],
    ) -> None:
        if plan.plan_type != "user" or plan.status != "active":
            return
        spec = self._spec(db, plan)
        if not spec["rules"] or any(rule["trigger"]["type"] != "delay" for rule in spec["rules"]):
            return
        states = (
            db.query(models.AutomationRuleState).filter_by(plan_id=plan.plan_id, version=plan.current_version).all()
        )
        terminal = {"executed", "failed", "missed"}
        statuses = {str((state.meta or {}).get("delay_status") or "") for state in states}
        if not statuses or not statuses.issubset(terminal):
            return
        all_executed = statuses == {"executed"}
        plan.status = "completed" if all_executed else "failed"
        plan.completed_at = utcnow()
        db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(synchronize_session=False)
        self._event(
            db,
            plan,
            None,
            "plan.completed" if all_executed else "plan.failed",
            {**detail, "delay_only": True, "succeeded": succeeded and all_executed},
        )

    def _schedule_retry(
        self,
        db: Session,
        plan: models.AutomationPlan,
        state: models.AutomationRuleState,
        detail: dict[str, Any],
    ) -> None:
        meta = dict(state.meta or {})
        retry_count = int(meta.get("retry_count") or 0) + 1
        meta["retry_count"] = retry_count
        if retry_count <= 3:
            delay = (5, 15, 60)[retry_count - 1]
            retry_after = utcnow() + timedelta(seconds=delay)
            meta["retry_after"] = retry_after.isoformat()
            meta.pop("retry_exhausted", None)
            state.blocked_reason = "command_retry"
            self._event(
                db,
                plan,
                state.rule_id,
                "command.retry_scheduled",
                {**detail, "attempt": retry_count, "retry_after": retry_after.isoformat()},
            )
        else:
            meta.pop("retry_after", None)
            meta["retry_exhausted"] = True
            state.blocked_reason = "command_retry_exhausted"
            self._event(
                db,
                plan,
                state.rule_id,
                "command.retry_exhausted",
                {**detail, "attempts": 3},
            )
        state.meta = meta

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
            "recommend_open_window": telemetry.recommend_open_window if telemetry else None,
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
                "recommend_open_window": sample.recommend_open_window,
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
        if event_type.startswith("plan.") or event_type in {"rule.claimed", "rule.released", "rule.conflict"}:
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
