from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.core.timeutil import iso_utc
from app.db import models
from app.domain.automation import DEFAULT_THRESHOLDS
from app.domain.commands import CommandRequest
from app.generated.command_catalog import COMMAND_CATALOG
from app.schemas import NotificationIn
from app.services.analysis import collect_device_snapshot
from app.services.commands import ensure_device
from app.services.events import serialize_event
from app.services.notifications import create_notification, list_notifications, serialize_notification
from app.services.telemetry import serialize_telemetry


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _bucket_points(points: list[dict[str, Any]], bucket_seconds: int) -> list[dict[str, Any]]:
    """Portable report-oriented bucketing used by both SQLite tests and PostgreSQL."""
    buckets: dict[int, list[dict[str, Any]]] = {}
    for point in points:
        sampled = datetime.fromisoformat(str(point["sampled_at"]).replace("Z", "+00:00"))
        key = int(sampled.timestamp()) // bucket_seconds * bucket_seconds
        buckets.setdefault(key, []).append(point)

    result: list[dict[str, Any]] = []
    for key in sorted(buckets, reverse=True):
        group = buckets[key]
        newest = dict(group[0])
        sensors = dict(newest.get("sensors") or {})
        for name in ("temperature_c", "humidity_percent", "tvoc_ppb", "hcho_ug_m3", "eco2_ppm"):
            values = [float(value) for point in group if (value := (point.get("sensors") or {}).get(name)) is not None]
            sensors[name] = sum(values) / len(values) if values else None
        newest["sampled_at"] = datetime.fromtimestamp(key, UTC).isoformat().replace("+00:00", "Z")
        newest["sensors"] = sensors
        newest["sample_count"] = len(group)
        result.append(newest)
    return result


class SqlAlchemyDeviceQueryRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def list_devices(self) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(models.Device).order_by(models.Device.device_id).all()
            return [
                {
                    "device_id": row.device_id,
                    "display_name": row.display_name,
                    "status": row.status,
                    "last_seen_at": iso_utc(row.last_seen_at),
                }
                for row in rows
            ]

    def snapshot(self, device_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            return collect_device_snapshot(db, device_id)

    def history(
        self,
        device_id: str,
        *,
        limit: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        bucket_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            query = db.query(models.Telemetry).filter(models.Telemetry.device_id == device_id)
            if start_at is not None:
                query = query.filter(models.Telemetry.sampled_at >= start_at)
            if end_at is not None:
                query = query.filter(models.Telemetry.sampled_at <= end_at)
            rows = query.order_by(models.Telemetry.sampled_at.desc()).limit(max(1, min(limit, 2000))).all()
            points = [serialize_telemetry(row) for row in rows]
            return _bucket_points(points, bucket_seconds) if bucket_seconds else points

    def events(self, device_id: str, *, limit: int) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = (
                db.query(models.DeviceEvent)
                .filter(models.DeviceEvent.device_id == device_id)
                .order_by(models.DeviceEvent.created_at.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            return [serialize_event(row) for row in rows]

    def capabilities(self, device_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(models.DeviceCapability).filter(models.DeviceCapability.device_id == device_id).one_or_none()
            if row is None:
                return None
            return {
                "device_id": device_id,
                "protocol_version": row.protocol_version,
                "firmware_version": row.firmware_version,
                "hardware_model": row.hardware_model,
                "commands": row.commands,
                "seen_at": iso_utc(row.seen_at),
            }

    def notifications(self, device_id: str, *, limit: int) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            return list_notifications(db, device_id, limit)

    def create_notification(self, device_id: str, content: str) -> dict[str, Any]:
        with self.session_factory() as db:
            notification, _ = create_notification(
                db,
                device_id,
                NotificationIn(content=content, voice_broadcast=False),
            )
            return serialize_notification(db, notification)

    def link_notification_command(self, notification_id: int, command_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            notification = db.get(models.Notification, notification_id)
            if notification is None:
                raise ValueError("notification not found")
            notification.voice_requested = True
            notification.voice_command_id = command_id
            db.add(notification)
            db.commit()
            db.refresh(notification)
            return serialize_notification(db, notification)

    def diagnostics_overview(self) -> dict[str, Any]:
        with self.session_factory() as db:

            def counts(field: Any) -> dict[str, int]:
                rows = db.query(field, func.count()).group_by(field).all()
                return {str(status): int(count) for status, count in rows}

            now = utcnow()
            workers = (
                db.query(models.RuntimeInstance)
                .filter(models.RuntimeInstance.role == "ai-worker")
                .order_by(models.RuntimeInstance.heartbeat_at.desc())
                .limit(10)
                .all()
            )
            capabilities = db.query(models.DeviceCapability).order_by(models.DeviceCapability.device_id).all()
            return {
                "ai_runs": counts(models.AiRun.status),
                "outbox": counts(models.OutboxMessage.status),
                "realtime": counts(models.RealtimeEvent.status),
                "workers": [
                    {
                        "instance_id": worker.instance_id,
                        "heartbeat_at": iso_utc(worker.heartbeat_at),
                        "role": worker.role,
                        "healthy": worker.heartbeat_at >= now - timedelta(seconds=45),
                        "age_seconds": max(0, int((now - worker.heartbeat_at).total_seconds())),
                    }
                    for worker in workers
                ],
                "capabilities": [
                    {
                        "device_id": row.device_id,
                        "firmware_version": row.firmware_version,
                        "hardware_model": row.hardware_model,
                        "command_count": len(row.commands or []),
                        "seen_at": iso_utc(row.seen_at),
                    }
                    for row in capabilities
                ],
            }

    def trace_timeline(self, trace_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            events = (
                db.query(models.TraceEvent)
                .filter(models.TraceEvent.trace_id == trace_id)
                .order_by(models.TraceEvent.occurred_at, models.TraceEvent.id)
                .all()
            )
            return {
                "trace_id": trace_id,
                "events": [
                    {
                        "event_id": event.event_id,
                        "trace_id": event.trace_id,
                        "device_id": event.device_id,
                        "component": event.component,
                        "event_type": event.event_type,
                        "status": event.status,
                        "detail": event.detail or {},
                        "occurred_at": iso_utc(event.occurred_at),
                    }
                    for event in events
                ],
            }


class SqlAlchemyCommandRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def device_status(self, device_id: str) -> str | None:
        with self.session_factory() as db:
            device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
            return device.status if device else None

    def supported_commands(self, device_id: str) -> set[str] | None:
        with self.session_factory() as db:
            capability = (
                db.query(models.DeviceCapability).filter(models.DeviceCapability.device_id == device_id).one_or_none()
            )
            if capability is None:
                return None
            return {str(item.get("name")) for item in capability.commands if isinstance(item, dict)}

    def guard_command(self, request: CommandRequest) -> tuple[str, str] | None:
        with self.session_factory() as db:
            sample = (
                db.query(models.Telemetry)
                .filter(models.Telemetry.device_id == request.device_id)
                .order_by(models.Telemetry.sampled_at.desc())
                .first()
            )
            if sample is not None:
                if request.type == "window.close" and sample.smoke_detected:
                    return "safety_interlock", "window cannot close while smoke is detected"
                if sample.control_priority == "manual_first":
                    if request.type.startswith("window.") and sample.manual_window_override:
                        return "policy_denied", "manual window override is active"
                    if request.type.startswith("led.") and sample.manual_led_override:
                        return "policy_denied", "manual LED override is active"
            recent = (
                db.query(models.Command)
                .filter(
                    models.Command.device_id == request.device_id,
                    models.Command.source.in_(["ai", "external_mcp"]),
                    models.Command.type == request.type,
                    models.Command.created_at >= utcnow() - timedelta(seconds=1),
                    models.Command.status.not_in(["rejected", "failed", "expired", "timed_out"]),
                )
                .first()
            )
            if recent is not None and recent.idempotency_key != request.idempotency_key:
                return "policy_denied", "AI command rate limit exceeded"
        return None

    def create_with_outbox(self, request: CommandRequest) -> dict[str, Any]:
        with self.session_factory() as db:
            if request.idempotency_key:
                existing = (
                    db.query(models.Command)
                    .filter(
                        models.Command.device_id == request.device_id,
                        models.Command.source == request.source,
                        models.Command.idempotency_key == request.idempotency_key,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    return serialize_v2_command(existing)
            ensure_device(db, request.device_id)
            from uuid import uuid4

            command = models.Command(
                command_id=f"cmd-{uuid4().hex[:16]}",
                device_id=request.device_id,
                type=request.type,
                parameter=request.parameter,
                source=request.source,
                confidence=1.0 if request.source in {"frontend", "external_mcp"} else 0.0,
                reason=request.reason,
                status="queued",
                trace_id=request.trace_id,
                idempotency_key=request.idempotency_key,
                expires_at=request.expires_at
                or utcnow() + timedelta(seconds=int(COMMAND_CATALOG[request.type]["default_ttl_seconds"])),
                raw_payload={"schema_version": "2.0"},
            )
            db.add(command)
            db.flush()
            command.created_at = command.created_at or utcnow()
            payload = mqtt_command_envelope(command)
            db.add(
                models.OutboxMessage(
                    command_id=command.command_id,
                    topic=f"devices/{request.device_id}/command",
                    payload=payload,
                    qos=1,
                    status="pending",
                    attempts=0,
                )
            )
            db.add(
                models.CommandEvent(
                    command_id=command.command_id,
                    trace_id=request.trace_id,
                    from_status="created",
                    to_status="queued",
                )
            )
            db.add(
                models.TraceEvent(
                    event_id=f"trace-{uuid4().hex[:20]}",
                    trace_id=request.trace_id,
                    device_id=request.device_id,
                    component="command",
                    event_type="command.queued",
                    status="queued",
                    detail={"command_id": command.command_id, "type": command.type, "source": command.source},
                )
            )
            desired = desired_state_patch(request.type)
            if desired:
                twin = (
                    db.query(models.DeviceTwin).filter(models.DeviceTwin.device_id == request.device_id).one_or_none()
                )
                if twin is None:
                    twin = models.DeviceTwin(device_id=request.device_id, desired_state={}, reported_state={})
                twin.desired_state = {**(twin.desired_state or {}), **desired}
                twin.desired_at = utcnow()
                db.add(twin)
            db.commit()
            db.refresh(command)
            return serialize_v2_command(command)

    def get(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            command = (
                db.query(models.Command)
                .filter(models.Command.device_id == device_id, models.Command.command_id == command_id)
                .one_or_none()
            )
            return serialize_v2_command(command) if command else None


def desired_state_patch(command_type: str) -> dict[str, Any]:
    return {
        "window.open": {"window_open": True},
        "window.close": {"window_open": False},
        "alarm.on": {"alarm_on": True},
        "alarm.off": {"alarm_on": False},
        "led.on": {"led_on": True},
        "led.off": {"led_on": False},
    }.get(command_type, {})


def mqtt_command_envelope(command: models.Command) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "message_id": command.command_id,
        "trace_id": command.trace_id,
        "device_id": command.device_id,
        "occurred_at": iso_utc(command.created_at or utcnow()),
        "boot_id": None,
        "sequence": None,
        "payload": {
            "command_id": command.command_id,
            "type": command.type,
            "parameter": command.parameter or {},
            "source": command.source,
            "issued_at": iso_utc(command.created_at or utcnow()),
            "expires_at": iso_utc(command.expires_at),
        },
    }


def serialize_v2_command(command: models.Command) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "trace_id": command.trace_id or "",
        "device_id": command.device_id,
        "type": command.type,
        "parameter": command.parameter or {},
        "source": command.source,
        "reason": command.reason or "",
        "status": command.status,
        "error_code": command.error_code,
        "created_at": iso_utc(command.created_at) if command.created_at else "",
        "expires_at": iso_utc(command.expires_at),
        "published_at": iso_utc(command.published_at),
        "accepted_at": iso_utc(command.accepted_at),
        "completed_at": iso_utc(command.executed_at),
        "capability": COMMAND_CATALOG.get(command.type),
    }


class SqlAlchemyAutomationRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def get_policy(self, device_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            ensure_device(db, device_id)
            policy = self._ensure(db, device_id)
            db.commit()
            db.refresh(policy)
            return serialize_policy(policy)

    def update_policy(self, device_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            ensure_device(db, device_id)
            policy = self._ensure(db, device_id)
            for name, value in changes.items():
                if value is not None and hasattr(policy, name):
                    setattr(policy, name, value)
            if policy.patrol_force_interval_seconds < policy.patrol_interval_seconds:
                raise ValueError("patrol force interval must be at least the patrol interval")
            db.add(policy)
            db.commit()
            db.refresh(policy)
            return serialize_policy(policy)

    @staticmethod
    def _ensure(db: Session, device_id: str) -> models.AutomationPolicy:
        policy = db.query(models.AutomationPolicy).filter(models.AutomationPolicy.device_id == device_id).one_or_none()
        if policy is None:
            policy = models.AutomationPolicy(device_id=device_id, thresholds=dict(DEFAULT_THRESHOLDS))
            db.add(policy)
            db.flush()
        return policy


class SqlAlchemyAiRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def create(self, device_id: str, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        from uuid import uuid4

        with self.session_factory() as db:
            ensure_device(db, device_id)
            run = models.AiRun(
                run_id=f"run-{uuid4().hex[:16]}",
                trace_id=trace_id,
                device_id=device_id,
                kind=str(payload["kind"]),
                trigger=str(payload.get("trigger") or "manual"),
                status="queued",
                input_payload=payload,
                available_at=utcnow(),
                max_attempts=3,
            )
            db.add(run)
            db.flush()
            db.add(
                models.TraceEvent(
                    event_id=f"trace-{uuid4().hex[:20]}",
                    trace_id=trace_id,
                    device_id=device_id,
                    component="ai",
                    event_type="ai.run.queued",
                    status="queued",
                    detail={"run_id": run.run_id, "kind": run.kind, "trigger": run.trigger},
                )
            )
            db.commit()
            db.refresh(run)
            return serialize_ai_run(db, run)

    def get(self, device_id: str, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            run = (
                db.query(models.AiRun)
                .filter(models.AiRun.device_id == device_id, models.AiRun.run_id == run_id)
                .one_or_none()
            )
            return serialize_ai_run(db, run) if run else None

    def list(self, device_id: str, kind: str | None, status: str | None, limit: int) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            query = db.query(models.AiRun).filter(models.AiRun.device_id == device_id)
            if kind:
                query = query.filter(models.AiRun.kind == kind)
            if status:
                query = query.filter(models.AiRun.status == status)
            rows = query.order_by(models.AiRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
            return [serialize_ai_run(db, row) for row in rows]

    def cancel(self, device_id: str, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            run = (
                db.query(models.AiRun)
                .filter(models.AiRun.device_id == device_id, models.AiRun.run_id == run_id)
                .one_or_none()
            )
            if run is None:
                return None
            if run.status == "queued":
                run.status = "cancelled"
                run.completed_at = utcnow()
            elif run.status in {"running", "waiting_model", "calling_tool", "waiting_device"}:
                run.cancel_requested_at = utcnow()
            db.add(run)
            db.commit()
            db.refresh(run)
            return serialize_ai_run(db, run)


def serialize_policy(policy: models.AutomationPolicy) -> dict[str, Any]:
    return {
        "device_id": policy.device_id,
        "enabled": policy.enabled,
        "event_trigger_enabled": policy.event_trigger_enabled,
        "patrol_enabled": policy.patrol_enabled,
        "patrol_interval_seconds": policy.patrol_interval_seconds,
        "patrol_force_interval_seconds": policy.patrol_force_interval_seconds,
        "vision_schedule_enabled": policy.vision_schedule_enabled,
        "vision_interval_seconds": policy.vision_interval_seconds,
        "sedentary_trigger_enabled": policy.sedentary_trigger_enabled,
        "sedentary_threshold_seconds": policy.sedentary_threshold_seconds,
        "execution_mode": policy.execution_mode,
        "thresholds": policy.thresholds or dict(DEFAULT_THRESHOLDS),
        "last_checked_at": iso_utc(policy.last_checked_at),
        "last_model_run_at": iso_utc(policy.last_model_run_at),
    }


def serialize_ai_run(db: Session, run: models.AiRun) -> dict[str, Any]:
    calls = (
        db.query(models.AiToolCall)
        .filter(models.AiToolCall.run_id == run.run_id)
        .order_by(models.AiToolCall.created_at.asc())
        .all()
    )
    return {
        "run_id": run.run_id,
        "trace_id": run.trace_id,
        "device_id": run.device_id,
        "kind": run.kind,
        "trigger": run.trigger,
        "status": run.status,
        "input": run.input_payload or {},
        "output": run.output_payload,
        "model": run.model or "",
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": iso_utc(run.created_at) if run.created_at else "",
        "started_at": iso_utc(run.started_at),
        "completed_at": iso_utc(run.completed_at),
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "cancel_requested_at": iso_utc(run.cancel_requested_at),
        "tool_calls": [
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "arguments": call.arguments or {},
                "result": call.result,
                "status": call.status,
                "error_message": call.error_message,
            }
            for call in calls
        ],
    }
