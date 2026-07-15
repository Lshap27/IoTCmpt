from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.timeutil import iso_utc
from app.db import models
from app.domain.automation import DEFAULT_THRESHOLDS
from app.domain.automation_plans import structural_diff, validate_plan_spec
from app.services.commands import ensure_device


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20]}"


def system_plan_id(device_id: str) -> str:
    digest = hashlib.sha256(device_id.encode()).hexdigest()[:20]
    return f"plan-system-lighting-{digest}"


SYSTEM_PLAN_VERSION = 2
SYSTEM_ENVIRONMENT_SPEC: dict[str, Any] = {
    "schema_version": "1.0",
    "title": "系统默认环境自动化",
    "duration_seconds": 86400,
    "timezone": "Asia/Shanghai",
    "manual_override_policy": "respect",
    "end_behavior": "keep_state",
    "clarifications": [],
    "rules": [
        {
            "id": "system-light-on",
            "description": "连续暗光且检测到人体时开启照明",
            "trigger": {
                "type": "condition",
                "mode": "all",
                "items": [
                    {"fact": "light_is_dark", "op": "eq", "value": True},
                    {"fact": "human_present", "op": "eq", "value": True},
                ],
                "stability_samples": 2,
            },
            "action": {"command": "led.on", "parameter": {}},
            "cooldown_seconds": 1,
        },
        {
            "id": "system-light-off",
            "description": "连续明亮且确认无人时关闭照明",
            "trigger": {
                "type": "condition",
                "mode": "all",
                "items": [
                    {"fact": "light_is_dark", "op": "eq", "value": False},
                    {"fact": "human_present", "op": "eq", "value": False},
                ],
                "stability_samples": 2,
            },
            "action": {"command": "led.off", "parameter": {}},
            "cooldown_seconds": 1,
        },
        {
            "id": "system-air-open",
            "description": "融合结果建议通风时打开窗户",
            "trigger": {
                "type": "condition",
                "mode": "all",
                "items": [{"fact": "recommend_open_window", "op": "eq", "value": True}],
                "stability_samples": 1,
            },
            "action": {"command": "window.open", "parameter": {}},
            "cooldown_seconds": 300,
        },
    ],
}


def _current_version(db: Session, plan: models.AutomationPlan) -> models.AutomationPlanVersion:
    return (
        db.query(models.AutomationPlanVersion)
        .filter(
            models.AutomationPlanVersion.plan_id == plan.plan_id,
            models.AutomationPlanVersion.version == plan.current_version,
        )
        .one()
    )


def serialize_plan(db: Session, plan: models.AutomationPlan) -> dict[str, Any]:
    version = _current_version(db, plan)
    states = (
        db.query(models.AutomationRuleState)
        .filter_by(plan_id=plan.plan_id, version=plan.current_version)
        .order_by(models.AutomationRuleState.rule_id.asc())
        .all()
    )
    claims = (
        db.query(models.AutomationActuatorClaim)
        .filter_by(plan_id=plan.plan_id, version=plan.current_version)
        .order_by(models.AutomationActuatorClaim.actuator.asc())
        .all()
    )
    return {
        "plan_id": plan.plan_id,
        "device_id": plan.device_id,
        "plan_type": plan.plan_type,
        "title": plan.title,
        "status": plan.status,
        "current_version": plan.current_version,
        "source_prompt": plan.source_prompt,
        "activation_blockers": plan.activation_blockers or [],
        "spec": version.spec,
        "explanation": version.explanation,
        "validation": version.validation or {},
        "rule_states": [
            {
                "rule_id": state.rule_id,
                "last_condition": state.last_condition,
                "last_fired_at": iso_utc(state.last_fired_at),
                "next_fire_at": iso_utc(state.next_fire_at),
                "last_command_id": state.last_command_id,
                "blocked_reason": state.blocked_reason,
            }
            for state in states
        ],
        "control_claims": [
            {
                "actuator": claim.actuator,
                "owner_type": claim.owner_type,
                "plan_id": claim.plan_id,
                "version": claim.version,
                "rule_ids": claim.rule_ids or [],
                "target_command": claim.target_command,
                "status": claim.status,
                "reason": claim.reason,
                "updated_at": iso_utc(claim.updated_at) or "",
            }
            for claim in claims
        ],
        "started_at": iso_utc(plan.started_at),
        "paused_at": iso_utc(plan.paused_at),
        "ends_at": iso_utc(plan.ends_at),
        "completed_at": iso_utc(plan.completed_at),
        "created_at": iso_utc(plan.created_at) or "",
        "updated_at": iso_utc(plan.updated_at) or "",
    }


def serialize_plan_event(event: models.AutomationPlanEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "plan_id": event.plan_id,
        "device_id": event.device_id,
        "version": event.version,
        "rule_id": event.rule_id,
        "trace_id": event.trace_id,
        "event_type": event.event_type,
        "detail": event.detail or {},
        "occurred_at": iso_utc(event.occurred_at) or "",
    }


def serialize_strategy(strategy: models.AiStrategy) -> dict[str, Any]:
    return {
        "strategy_id": strategy.strategy_id,
        "device_id": strategy.device_id,
        "run_id": strategy.run_id,
        "plan_id": strategy.plan_id,
        "base_version": strategy.base_version,
        "proposed_spec": strategy.proposed_spec,
        "diff": strategy.diff or [],
        "summary": strategy.summary,
        "status": strategy.status,
        "created_at": iso_utc(strategy.created_at) or "",
        "resolved_at": iso_utc(strategy.resolved_at),
    }


class SqlAlchemyAutomationPlanRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def ensure_system_plan(self, device_id: str) -> dict[str, Any]:
        plan_id = system_plan_id(device_id)
        with self.session_factory() as db:
            ensure_device(db, device_id)
            plan = db.query(models.AutomationPlan).filter(models.AutomationPlan.plan_id == plan_id).one_or_none()
            if plan is None:
                now = utcnow()
                spec = validate_plan_spec(SYSTEM_ENVIRONMENT_SPEC)
                plan = models.AutomationPlan(
                    plan_id=plan_id,
                    device_id=device_id,
                    plan_type="system",
                    title=spec["title"],
                    status="active",
                    current_version=SYSTEM_PLAN_VERSION,
                    source_prompt="system-default-environment",
                    activation_blockers=[],
                    started_at=now,
                )
                db.add(plan)
                db.add(
                    models.AutomationPlanVersion(
                        plan_id=plan_id,
                        version=SYSTEM_PLAN_VERSION,
                        spec=spec,
                        explanation="由确定性灯光与空气通风规则组成的系统计划",
                        validation={"valid": True, "system": True, "managed_version": SYSTEM_PLAN_VERSION},
                    )
                )
                legacy = db.get(models.LightingRuleState, device_id)
                for rule in spec["rules"]:
                    inherited = legacy if legacy and rule["id"].startswith("system-light-") else None
                    db.add(
                        models.AutomationRuleState(
                            plan_id=plan_id,
                            version=SYSTEM_PLAN_VERSION,
                            rule_id=rule["id"],
                            last_condition=inherited.condition if inherited else "unknown",
                            last_command_id=inherited.last_action_command_id if inherited else None,
                            meta={
                                "legacy_speech_command_id": inherited.speech_command_id if inherited else None,
                                "system": True,
                            },
                        )
                    )
                self._event(db, plan, None, "plan.created", {"system": True})
                db.commit()
                db.refresh(plan)
            elif plan.current_version < SYSTEM_PLAN_VERSION:
                self._upgrade_system_plan(db, plan)
            return serialize_plan(db, plan)

    def _upgrade_system_plan(self, db: Session, plan: models.AutomationPlan) -> None:
        previous_version = plan.current_version
        previous_states = {
            row.rule_id: row
            for row in db.query(models.AutomationRuleState).filter_by(plan_id=plan.plan_id, version=previous_version)
        }
        spec = validate_plan_spec(SYSTEM_ENVIRONMENT_SPEC)
        version = (
            db.query(models.AutomationPlanVersion)
            .filter_by(plan_id=plan.plan_id, version=SYSTEM_PLAN_VERSION)
            .one_or_none()
        )
        if version is None:
            db.add(
                models.AutomationPlanVersion(
                    plan_id=plan.plan_id,
                    version=SYSTEM_PLAN_VERSION,
                    spec=spec,
                    explanation="系统计划加入融合空气通风规则",
                    validation={
                        "valid": True,
                        "system": True,
                        "managed_version": SYSTEM_PLAN_VERSION,
                        "upgraded_from": previous_version,
                    },
                )
            )
        for rule in spec["rules"]:
            existing = (
                db.query(models.AutomationRuleState)
                .filter_by(plan_id=plan.plan_id, version=SYSTEM_PLAN_VERSION, rule_id=rule["id"])
                .one_or_none()
            )
            if existing is not None:
                continue
            prior = previous_states.get(rule["id"])
            db.add(
                models.AutomationRuleState(
                    plan_id=plan.plan_id,
                    version=SYSTEM_PLAN_VERSION,
                    rule_id=rule["id"],
                    last_condition=prior.last_condition if prior else "unknown",
                    stable_count=prior.stable_count if prior else 0,
                    last_fired_at=prior.last_fired_at if prior else None,
                    next_fire_at=prior.next_fire_at if prior else None,
                    last_command_id=prior.last_command_id if prior else None,
                    last_occurrence_key=prior.last_occurrence_key if prior else None,
                    blocked_reason=prior.blocked_reason if prior else None,
                    meta={**(prior.meta or {})} if prior else {"system": True},
                )
            )
        db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(synchronize_session=False)
        plan.title = spec["title"]
        plan.current_version = SYSTEM_PLAN_VERSION
        plan.source_prompt = "system-default-environment"
        self._event(
            db,
            plan,
            None,
            "plan.version_upgraded",
            {"from_version": previous_version, "to_version": SYSTEM_PLAN_VERSION},
        )
        db.commit()
        db.refresh(plan)

    def create_draft(
        self,
        device_id: str,
        source_prompt: str,
        spec: dict[str, Any],
        explanation: str,
        source_ai_run_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]:
        normalized = validate_plan_spec(spec)
        with self.session_factory() as db:
            ensure_device(db, device_id)
            self._lock_device(db, device_id)
            policy = self._ensure_policy(db, device_id)
            capability = (
                db.query(models.DeviceCapability).filter(models.DeviceCapability.device_id == device_id).one_or_none()
            )
            advertised = {str(row.get("name")) for row in (capability.commands if capability else [])}
            commands = {str(rule["action"]["command"]) for rule in normalized["rules"]}
            blockers = list(normalized["clarifications"])
            if not policy.enabled:
                blockers.append("automation_policy_disabled")
            if capability is None:
                blockers.append("capabilities_unknown")
            else:
                missing = sorted(commands - advertised)
                blockers.extend(f"unsupported_command:{name}" for name in missing)
            active = self._active_user_plan(db, device_id)
            if active is not None:
                blockers.append(f"active_plan:{active.plan_id}")
            now = utcnow()
            plan = models.AutomationPlan(
                plan_id=_id("plan"),
                device_id=device_id,
                plan_type="user",
                title=normalized["title"],
                status="draft" if blockers else "active",
                current_version=1,
                source_prompt=source_prompt,
                activation_blockers=blockers,
                started_at=None if blockers else now,
                ends_at=None if blockers else now + timedelta(seconds=normalized["duration_seconds"]),
            )
            db.add(plan)
            db.flush()
            db.add(
                models.AutomationPlanVersion(
                    plan_id=plan.plan_id,
                    version=1,
                    source_ai_run_id=source_ai_run_id,
                    spec=normalized,
                    explanation=explanation,
                    validation={"valid": True, "auto_activated": not blockers, "blockers": blockers},
                )
            )
            self._initialize_states(db, plan, normalized, now)
            self._event(
                db,
                plan,
                None,
                "plan.activated" if not blockers else "plan.draft_created",
                {"auto_activated": not blockers, "blockers": blockers},
                trace_id=trace_id,
            )
            db.commit()
            db.refresh(plan)
            return serialize_plan(db, plan)

    def list_plans(self, device_id: str) -> list[dict[str, Any]]:
        self.ensure_system_plan(device_id)
        with self.session_factory() as db:
            rows = (
                db.query(models.AutomationPlan)
                .filter(models.AutomationPlan.device_id == device_id)
                .order_by(models.AutomationPlan.created_at.desc())
                .all()
            )
            return [serialize_plan(db, row) for row in rows]

    def get(self, device_id: str, plan_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            plan = (
                db.query(models.AutomationPlan)
                .filter(models.AutomationPlan.device_id == device_id, models.AutomationPlan.plan_id == plan_id)
                .one_or_none()
            )
            return serialize_plan(db, plan) if plan else None

    def events(self, device_id: str, plan_id: str, limit: int) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            if not db.query(models.AutomationPlan).filter_by(device_id=device_id, plan_id=plan_id).first():
                return []
            rows = (
                db.query(models.AutomationPlanEvent)
                .filter(models.AutomationPlanEvent.plan_id == plan_id)
                .order_by(models.AutomationPlanEvent.occurred_at.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            return [serialize_plan_event(row) for row in rows]

    def transition(self, device_id: str, plan_id: str, action: str, replace_active: bool = False) -> dict[str, Any]:
        now = utcnow()
        with self.session_factory() as db:
            self._lock_device(db, device_id)
            plan = (
                db.query(models.AutomationPlan)
                .filter(models.AutomationPlan.device_id == device_id, models.AutomationPlan.plan_id == plan_id)
                .one_or_none()
            )
            if plan is None:
                raise ValueError("automation plan not found")
            if plan.plan_type == "system" and action in {"activate", "cancel"}:
                raise ValueError("system plan lifecycle is controlled by automation policy")
            spec = _current_version(db, plan).spec
            if action == "activate":
                if plan.status not in {"draft", "paused"}:
                    raise ValueError("only draft or paused plans can be activated")
                active = self._active_user_plan(db, device_id, exclude=plan.plan_id)
                if active is not None:
                    if not replace_active:
                        raise ValueError(f"active plan exists: {active.plan_id}")
                    active.status = "superseded"
                    active.completed_at = now
                    db.query(models.AutomationActuatorClaim).filter_by(plan_id=active.plan_id).delete(
                        synchronize_session=False
                    )
                    self._event(db, active, None, "plan.superseded", {"replacement_plan_id": plan.plan_id})
                blockers = self._activation_blockers(db, device_id, spec, exclude=plan.plan_id)
                if blockers:
                    plan.activation_blockers = blockers
                    raise ValueError("plan activation blocked: " + ", ".join(blockers))
                if plan.status == "paused" and plan.paused_at:
                    pause_duration = now - plan.paused_at
                    if plan.ends_at:
                        plan.ends_at += pause_duration
                    for state in db.query(models.AutomationRuleState).filter_by(
                        plan_id=plan.plan_id, version=plan.current_version
                    ):
                        if state.next_fire_at:
                            state.next_fire_at += pause_duration
                else:
                    plan.started_at = now
                    plan.ends_at = now + timedelta(seconds=int(spec["duration_seconds"]))
                    self._reset_states(db, plan, spec, now)
                plan.paused_at = None
                plan.status = "active"
                plan.activation_blockers = []
                event_type = "plan.activated"
            elif action == "pause":
                if plan.status != "active":
                    raise ValueError("only active plans can be paused")
                plan.status = "paused"
                plan.paused_at = now
                db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(
                    synchronize_session=False
                )
                event_type = "plan.paused"
            elif action == "resume":
                if plan.status != "paused":
                    raise ValueError("only paused plans can be resumed")
                pause_duration = now - (plan.paused_at or now)
                if plan.ends_at:
                    plan.ends_at += pause_duration
                for state in db.query(models.AutomationRuleState).filter_by(
                    plan_id=plan.plan_id, version=plan.current_version
                ):
                    if state.next_fire_at:
                        state.next_fire_at += pause_duration
                plan.paused_at = None
                plan.status = "active"
                event_type = "plan.resumed"
            elif action == "cancel":
                if plan.status not in {"draft", "active", "paused"}:
                    raise ValueError("plan is already terminal")
                plan.status = "cancelled"
                plan.completed_at = now
                db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(
                    synchronize_session=False
                )
                event_type = "plan.cancelled"
            else:
                raise ValueError(f"unsupported plan action: {action}")
            self._event(db, plan, None, event_type, {})
            db.commit()
            db.refresh(plan)
            return serialize_plan(db, plan)

    def propose_strategy(
        self,
        device_id: str,
        run_id: str,
        plan_id: str | None,
        base_version: int | None,
        proposed_spec: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        normalized = validate_plan_spec(proposed_spec)
        with self.session_factory() as db:
            base_spec = None
            if plan_id:
                plan = db.query(models.AutomationPlan).filter_by(device_id=device_id, plan_id=plan_id).one_or_none()
                if plan is None:
                    raise ValueError("base automation plan not found")
                if base_version != plan.current_version:
                    raise ValueError("base plan version is stale")
                base_spec = _current_version(db, plan).spec
            diff = structural_diff(base_spec, normalized)
            strategy = models.AiStrategy(
                strategy_id=_id("strategy"),
                device_id=device_id,
                run_id=run_id,
                plan_id=plan_id,
                base_version=base_version,
                proposed_spec=normalized,
                diff=diff,
                summary=summary,
                status="proposed" if diff else "skipped",
                resolved_at=utcnow() if not diff else None,
            )
            db.add(strategy)
            self._strategy_realtime(db, strategy)
            db.commit()
            db.refresh(strategy)
            return serialize_strategy(strategy)

    def list_strategies(self, device_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = (
                db.query(models.AiStrategy)
                .filter(models.AiStrategy.device_id == device_id)
                .order_by(models.AiStrategy.created_at.desc())
                .limit(100)
                .all()
            )
            return [serialize_strategy(row) for row in rows]

    def get_strategy(self, device_id: str, strategy_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(models.AiStrategy).filter_by(device_id=device_id, strategy_id=strategy_id).one_or_none()
            return serialize_strategy(row) if row else None

    def resolve_strategy(self, device_id: str, strategy_id: str, action: str) -> dict[str, Any]:
        now = utcnow()
        with self.session_factory() as db:
            self._lock_device(db, device_id)
            strategy = db.query(models.AiStrategy).filter_by(device_id=device_id, strategy_id=strategy_id).one_or_none()
            if strategy is None:
                raise ValueError("AI strategy not found")
            if strategy.status != "proposed":
                raise ValueError("AI strategy is not pending")
            if action == "reject":
                strategy.status = "rejected"
                strategy.resolved_at = now
            elif action == "approve":
                if strategy.plan_id:
                    plan = (
                        db.query(models.AutomationPlan)
                        .filter_by(device_id=device_id, plan_id=strategy.plan_id)
                        .one_or_none()
                    )
                    if plan is None or plan.current_version != strategy.base_version:
                        raise RuntimeError("strategy base version is stale")
                    spec = validate_plan_spec(strategy.proposed_spec)
                    blockers = self._activation_blockers(db, device_id, spec, exclude=plan.plan_id)
                    if blockers:
                        raise ValueError(f"strategy cannot be approved: {', '.join(blockers)}")
                    next_version = plan.current_version + 1
                    db.add(
                        models.AutomationPlanVersion(
                            plan_id=plan.plan_id,
                            version=next_version,
                            source_ai_run_id=strategy.run_id,
                            spec=spec,
                            explanation=strategy.summary,
                            validation={"valid": True, "approved_strategy_id": strategy.strategy_id},
                        )
                    )
                    self._copy_or_initialize_states(db, plan, spec, next_version, now)
                    db.query(models.AutomationActuatorClaim).filter_by(plan_id=plan.plan_id).delete(
                        synchronize_session=False
                    )
                    plan.current_version = next_version
                    plan.title = spec["title"]
                    self._event(db, plan, None, "plan.version_activated", {"strategy_id": strategy.strategy_id})
                else:
                    spec = validate_plan_spec(strategy.proposed_spec)
                    blockers = self._activation_blockers(db, device_id, spec)
                    if blockers:
                        raise ValueError(f"strategy cannot be approved: {', '.join(blockers)}")
                    plan = models.AutomationPlan(
                        plan_id=_id("plan"),
                        device_id=device_id,
                        plan_type="user",
                        title=spec["title"],
                        status="active",
                        current_version=1,
                        source_prompt="approved AI strategy",
                        activation_blockers=[],
                        started_at=now,
                        ends_at=now + timedelta(seconds=spec["duration_seconds"]),
                    )
                    db.add(plan)
                    db.flush()
                    db.add(
                        models.AutomationPlanVersion(
                            plan_id=plan.plan_id,
                            version=1,
                            source_ai_run_id=strategy.run_id,
                            spec=spec,
                            explanation=strategy.summary,
                            validation={"valid": True, "approved_strategy_id": strategy.strategy_id},
                        )
                    )
                    self._initialize_states(db, plan, spec, now)
                    strategy.plan_id = plan.plan_id
                    strategy.base_version = 1
                    self._event(db, plan, None, "plan.activated", {"strategy_id": strategy.strategy_id})
                strategy.status = "approved"
                strategy.resolved_at = now
            else:
                raise ValueError(f"unsupported strategy action: {action}")
            self._strategy_realtime(db, strategy)
            db.commit()
            db.refresh(strategy)
            return serialize_strategy(strategy)

    @staticmethod
    def _ensure_policy(db: Session, device_id: str) -> models.AutomationPolicy:
        policy = db.query(models.AutomationPolicy).filter_by(device_id=device_id).one_or_none()
        if policy is None:
            policy = models.AutomationPolicy(device_id=device_id, thresholds=dict(DEFAULT_THRESHOLDS))
            db.add(policy)
            db.flush()
        return policy

    @staticmethod
    def _lock_device(db: Session, device_id: str) -> None:
        query = db.query(models.Device).filter(models.Device.device_id == device_id)
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        if query.one_or_none() is None:
            ensure_device(db, device_id)

    @staticmethod
    def _active_user_plan(db: Session, device_id: str, exclude: str | None = None) -> models.AutomationPlan | None:
        query = db.query(models.AutomationPlan).filter(
            models.AutomationPlan.device_id == device_id,
            models.AutomationPlan.plan_type == "user",
            models.AutomationPlan.status.in_(["active", "paused"]),
        )
        if exclude:
            query = query.filter(models.AutomationPlan.plan_id != exclude)
        return query.first()

    def _activation_blockers(
        self, db: Session, device_id: str, spec: dict[str, Any], exclude: str | None = None
    ) -> list[str]:
        blockers = list(spec.get("clarifications") or [])
        policy = self._ensure_policy(db, device_id)
        if not policy.enabled:
            blockers.append("automation_policy_disabled")
        active = self._active_user_plan(db, device_id, exclude=exclude)
        if active:
            blockers.append(f"active_plan:{active.plan_id}")
        capability = db.query(models.DeviceCapability).filter_by(device_id=device_id).one_or_none()
        if capability is None:
            blockers.append("capabilities_unknown")
        else:
            advertised = {str(row.get("name")) for row in capability.commands}
            requested = {str(rule["action"]["command"]) for rule in spec["rules"]}
            blockers.extend(f"unsupported_command:{name}" for name in sorted(requested - advertised))
        return blockers

    @staticmethod
    def _initialize_states(db: Session, plan: models.AutomationPlan, spec: dict[str, Any], now: datetime) -> None:
        for rule in spec["rules"]:
            trigger = rule["trigger"]
            next_fire = now + timedelta(seconds=trigger["every_seconds"]) if trigger["type"] == "interval" else None
            db.add(
                models.AutomationRuleState(
                    plan_id=plan.plan_id,
                    version=plan.current_version,
                    rule_id=rule["id"],
                    next_fire_at=next_fire,
                    meta={},
                )
            )

    @staticmethod
    def _reset_states(db: Session, plan: models.AutomationPlan, spec: dict[str, Any], now: datetime) -> None:
        db.query(models.AutomationRuleState).filter_by(plan_id=plan.plan_id, version=plan.current_version).delete()
        SqlAlchemyAutomationPlanRepository._initialize_states(db, plan, spec, now)

    @staticmethod
    def _copy_or_initialize_states(
        db: Session, plan: models.AutomationPlan, spec: dict[str, Any], version: int, now: datetime
    ) -> None:
        old_spec = _current_version(db, plan).spec
        old_rules = {row["id"]: row for row in old_spec["rules"]}
        old_states = {
            row.rule_id: row
            for row in db.query(models.AutomationRuleState).filter_by(
                plan_id=plan.plan_id, version=plan.current_version
            )
        }
        for rule in spec["rules"]:
            old = old_states.get(rule["id"])
            unchanged = old is not None and old_rules.get(rule["id"]) == rule
            preserved = old if unchanged else None
            trigger = rule["trigger"]
            next_fire = (
                preserved.next_fire_at
                if preserved is not None
                else now + timedelta(seconds=trigger["every_seconds"])
                if trigger["type"] == "interval"
                else None
            )
            db.add(
                models.AutomationRuleState(
                    plan_id=plan.plan_id,
                    version=version,
                    rule_id=rule["id"],
                    last_condition=preserved.last_condition if preserved is not None else "unknown",
                    stable_count=preserved.stable_count if preserved is not None else 0,
                    last_fired_at=preserved.last_fired_at if preserved is not None else None,
                    next_fire_at=next_fire,
                    last_command_id=preserved.last_command_id if preserved is not None else None,
                    last_occurrence_key=preserved.last_occurrence_key if preserved is not None else None,
                    blocked_reason=preserved.blocked_reason if preserved is not None else None,
                    meta=dict(preserved.meta or {}) if preserved is not None else {},
                )
            )

    @staticmethod
    def _event(
        db: Session,
        plan: models.AutomationPlan,
        rule_id: str | None,
        event_type: str,
        detail: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> None:
        event_id = _id("plan-event")
        payload = {
            "event_id": event_id,
            "plan_id": plan.plan_id,
            "version": plan.current_version,
            "rule_id": rule_id,
            "event_type": event_type,
            "detail": detail,
        }
        db.add(
            models.AutomationPlanEvent(
                event_id=event_id,
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
                event_id=_id("evt"),
                device_id=plan.device_id,
                trace_id=trace_id,
                type="automation.plan.event",
                payload=payload,
            )
        )
        db.add(
            models.RealtimeEvent(
                event_id=_id("evt"),
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

    @staticmethod
    def _strategy_realtime(db: Session, strategy: models.AiStrategy) -> None:
        db.add(
            models.RealtimeEvent(
                event_id=_id("evt"),
                device_id=strategy.device_id,
                type="automation.strategy.changed",
                payload=serialize_strategy(strategy),
            )
        )
