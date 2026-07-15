from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.application.commands import CommandApplicationService
from app.db import models
from app.domain.commands import CommandRejected, CommandRequest
from app.services.voice_commands import submit_speech

POSE_MAX_AGE_SECONDS = 15
LIGHT_ON_SPEECH = "检测到环境光线较暗，已为您打开照明。"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class LightingAutomationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        commands: CommandApplicationService,
    ) -> None:
        self.session_factory = session_factory
        self.commands = commands
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def evaluate(self, device_id: str) -> dict[str, Any] | None:
        async with self._locks[device_id]:
            pending_action = await asyncio.to_thread(self._pending_action_command, device_id)
            if pending_action:
                await self._reconcile_command_locked(device_id, pending_action)
            candidate = await asyncio.to_thread(self._candidate, device_id)
            if candidate is None or candidate["skip"]:
                return None
            trace_id = f"trace-{uuid4().hex[:16]}"
            try:
                command = await self.commands.submit(
                    CommandRequest(
                        device_id=device_id,
                        type=candidate["command_type"],
                        source="rule",
                        reason=candidate["reason"],
                        trace_id=trace_id,
                        idempotency_key=candidate["idempotency_key"],
                    ),
                    ai_restricted=True,
                )
            except CommandRejected as exc:
                await asyncio.to_thread(
                    self._save_evaluation,
                    device_id,
                    candidate,
                    None,
                    f"blocked:{exc.error_code}",
                )
                return None
            await asyncio.to_thread(
                self._save_evaluation,
                device_id,
                candidate,
                command["command_id"],
                candidate["condition"],
            )
            await self._reconcile_command_locked(device_id, command["command_id"])
            return command

    async def reconcile_command(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        async with self._locks[device_id]:
            return await self._reconcile_command_locked(device_id, command_id)

    async def _reconcile_command_locked(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        state = await asyncio.to_thread(self._speech_candidate, device_id, command_id)
        if state is None:
            return None
        speech = await submit_speech(
            self.commands,
            device_id=device_id,
            text=LIGHT_ON_SPEECH,
            source="rule",
            reason="lighting automation completed",
            trace_id=state["trace_id"],
            idempotency_key=f"lighting-speech:{command_id}",
        )
        await asyncio.to_thread(self._save_speech_command, device_id, command_id, speech["command_id"])
        return speech

    def _candidate(self, device_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            if (
                db.query(models.AutomationPlan)
                .filter_by(device_id=device_id, plan_type="system", status="active")
                .first()
                is not None
            ):
                return None
            policy = (
                db.query(models.AutomationPolicy).filter(models.AutomationPolicy.device_id == device_id).one_or_none()
            )
            if policy is not None and not policy.enabled:
                return None
            samples = (
                db.query(models.Telemetry)
                .filter(models.Telemetry.device_id == device_id)
                .order_by(models.Telemetry.sampled_at.desc(), models.Telemetry.id.desc())
                .limit(2)
                .all()
            )
            if len(samples) < 2 or samples[0].light_is_dark is None:
                return None
            if samples[0].light_is_dark != samples[1].light_is_dark:
                return None
            pose = (
                db.query(models.PoseResult)
                .filter(models.PoseResult.device_id == device_id)
                .order_by(models.PoseResult.created_at.desc(), models.PoseResult.id.desc())
                .first()
            )
            if (
                pose is None
                or not pose.created_at
                or pose.created_at < utcnow() - timedelta(seconds=POSE_MAX_AGE_SECONDS)
            ):
                return None

            latest = samples[0]
            if latest.light_is_dark and pose.human_present:
                condition, command_type = "dark_present", "led.on"
                reason = "two dark samples and recent presence detection"
                desired = True
            elif not latest.light_is_dark and not pose.human_present:
                condition, command_type = "bright_empty", "led.off"
                reason = "two bright samples and recent absence detection"
                desired = False
            else:
                condition, command_type, reason, desired = "hold", "", "", None

            if latest.control_priority == "manual_first" and latest.manual_led_override:
                condition = f"manual_blocked:{condition}"
                command_type = ""

            state = db.get(models.LightingRuleState, device_id)
            skip = condition == "hold" or not command_type or latest.led_on is desired
            if state is not None and state.condition == condition:
                skip = True
            return {
                "condition": condition,
                "command_type": command_type,
                "reason": reason,
                "telemetry_id": latest.id,
                "pose_result_id": pose.id,
                "idempotency_key": f"lighting:{latest.id}:{pose.id}:{command_type}",
                "skip": skip,
            }

    def _save_evaluation(
        self,
        device_id: str,
        candidate: dict[str, Any],
        command_id: str | None,
        condition: str,
    ) -> None:
        with self.session_factory() as db:
            state = db.get(models.LightingRuleState, device_id) or models.LightingRuleState(device_id=device_id)
            state.condition = condition
            state.last_telemetry_id = candidate["telemetry_id"]
            state.last_pose_result_id = candidate["pose_result_id"]
            state.last_action_command_id = command_id
            state.speech_command_id = None
            db.add(state)
            db.commit()

    def _speech_candidate(self, device_id: str, command_id: str) -> dict[str, str] | None:
        with self.session_factory() as db:
            state = db.get(models.LightingRuleState, device_id)
            legacy_matches = bool(state and state.last_action_command_id == command_id and not state.speech_command_id)
            generic = (
                db.query(models.AutomationRuleState)
                .join(models.AutomationPlan, models.AutomationPlan.plan_id == models.AutomationRuleState.plan_id)
                .filter(
                    models.AutomationPlan.device_id == device_id,
                    models.AutomationPlan.plan_type == "system",
                    models.AutomationRuleState.rule_id == "system-light-on",
                    models.AutomationRuleState.last_command_id == command_id,
                )
                .first()
            )
            generic_matches = bool(generic and not (generic.meta or {}).get("speech_command_id"))
            if not legacy_matches and not generic_matches:
                return None
            command = (
                db.query(models.Command)
                .filter(models.Command.device_id == device_id, models.Command.command_id == command_id)
                .one_or_none()
            )
            if command is None or command.type != "led.on" or command.status != "executed":
                return None
            return {"trace_id": command.trace_id or f"trace-{uuid4().hex[:16]}"}

    def _pending_action_command(self, device_id: str) -> str | None:
        with self.session_factory() as db:
            state = db.get(models.LightingRuleState, device_id)
            if state is not None and not state.speech_command_id and state.last_action_command_id:
                return state.last_action_command_id
            generic = (
                db.query(models.AutomationRuleState)
                .join(models.AutomationPlan, models.AutomationPlan.plan_id == models.AutomationRuleState.plan_id)
                .filter(
                    models.AutomationPlan.device_id == device_id,
                    models.AutomationPlan.plan_type == "system",
                    models.AutomationRuleState.rule_id == "system-light-on",
                    models.AutomationRuleState.last_command_id.is_not(None),
                )
                .first()
            )
            if generic is None or (generic.meta or {}).get("speech_command_id"):
                return None
            return generic.last_command_id

    def _save_speech_command(self, device_id: str, action_command_id: str, speech_command_id: str) -> None:
        with self.session_factory() as db:
            state = db.get(models.LightingRuleState, device_id)
            if state is not None and state.last_action_command_id == action_command_id:
                state.speech_command_id = speech_command_id
                db.add(state)
            generic = (
                db.query(models.AutomationRuleState)
                .filter(
                    models.AutomationRuleState.rule_id == "system-light-on",
                    models.AutomationRuleState.last_command_id == action_command_id,
                )
                .first()
            )
            if generic is not None:
                generic.meta = {**(generic.meta or {}), "speech_command_id": speech_command_id}
                db.add(generic)
            db.commit()
