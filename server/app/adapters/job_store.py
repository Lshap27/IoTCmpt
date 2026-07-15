from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.db import models

ACTIVE_RUN_STATUSES = {"running", "waiting_model", "calling_tool", "waiting_device"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled", "skipped"}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RunCancelled(RuntimeError):
    pass


class RunLeaseLost(RuntimeError):
    pass


class SqlAlchemyJobStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        instance_id: str,
        *,
        lease_seconds: int = 90,
        max_attempts: int = 3,
    ):
        self.session_factory = session_factory
        self.instance_id = instance_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def heartbeat_instance(self, meta: dict[str, Any] | None = None) -> None:
        now = utcnow()
        with self.session_factory() as db:
            row = db.get(models.RuntimeInstance, self.instance_id)
            if row is None:
                row = models.RuntimeInstance(
                    instance_id=self.instance_id,
                    role="ai-worker",
                    started_at=now,
                    heartbeat_at=now,
                    meta=meta or {},
                )
            else:
                row.heartbeat_at = now
                row.meta = meta or row.meta
            db.add(row)
            db.commit()

    def claim_next(self) -> dict[str, Any] | None:
        self.recover_expired()
        now = utcnow()
        with self.session_factory() as db:
            query = (
                db.query(models.AiRun)
                .filter(
                    models.AiRun.status == "queued",
                    (models.AiRun.available_at.is_(None)) | (models.AiRun.available_at <= now),
                )
                .order_by(models.AiRun.created_at.asc())
            )
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            run = query.first()
            if run is None:
                return None
            run.status = "running"
            run.started_at = run.started_at or now
            run.attempt_count += 1
            run.max_attempts = run.max_attempts or self.max_attempts
            run.lease_owner = self.instance_id
            run.lease_token = str(uuid4())
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            run.heartbeat_at = now
            self._append_events(db, run, "ai.run.running", "running")
            db.commit()
            return self._run_dict(run)

    def recover_expired(self) -> int:
        now = utcnow()
        changed = 0
        with self.session_factory() as db:
            rows = (
                db.query(models.AiRun)
                .filter(models.AiRun.status.in_(ACTIVE_RUN_STATUSES), models.AiRun.lease_expires_at < now)
                .all()
            )
            for run in rows:
                if run.attempt_count >= (run.max_attempts or self.max_attempts):
                    run.status = "failed"
                    run.error_code = "worker_lost"
                    run.error_message = "worker lease expired"
                    run.completed_at = now
                else:
                    run.status = "queued"
                    run.available_at = now + timedelta(seconds=min(30, 2 ** max(run.attempt_count, 1)))
                run.lease_owner = None
                run.lease_token = None
                run.lease_expires_at = None
                self._append_events(db, run, "ai.run.lease_expired", run.status)
                changed += 1
            db.commit()
        return changed

    def renew(self, run_id: str, lease_token: str) -> bool:
        now = utcnow()
        with self.session_factory() as db:
            run = (
                db.query(models.AiRun)
                .filter(
                    models.AiRun.run_id == run_id,
                    models.AiRun.lease_owner == self.instance_id,
                    models.AiRun.lease_token == lease_token,
                    models.AiRun.lease_expires_at >= now,
                )
                .one_or_none()
            )
            if run is None or run.status not in ACTIVE_RUN_STATUSES:
                return False
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            db.add(run)
            db.commit()
            return True

    def ensure_owned(self, run_id: str, lease_token: str) -> None:
        with self.session_factory() as db:
            self._owned_run(db, run_id, lease_token)

    def transition(
        self,
        run_id: str,
        status: str,
        lease_token: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as db:
            run = self._owned_run(db, run_id, lease_token)
            if run.cancel_requested_at is not None:
                run.status = "cancelled"
                run.completed_at = utcnow()
                run.lease_owner = None
                run.lease_token = None
                run.lease_expires_at = None
                self._append_events(db, run, "ai.run.cancelled", "cancelled")
                db.commit()
                raise RunCancelled(run_id)
            run.status = status
            self._append_events(db, run, f"ai.run.{status}", status, detail)
            db.commit()
            return self._run_dict(run)

    def complete(self, run_id: str, output: dict[str, Any], model: str, lease_token: str) -> None:
        now = utcnow()
        with self.session_factory() as db:
            run = self._owned_run(db, run_id, lease_token)
            if run.cancel_requested_at is not None:
                run.status = "cancelled"
                run.completed_at = now
                run.lease_owner = None
                run.lease_token = None
                run.lease_expires_at = None
                self._append_events(db, run, "ai.run.cancelled", "cancelled")
                db.commit()
                raise RunCancelled(run_id)
            strategy_status = (output.get("strategy") or {}).get("status") if run.kind == "strategy" else None
            run.status = "skipped" if strategy_status == "skipped" else "succeeded"
            run.output_payload = output
            run.model = model
            run.completed_at = now
            run.lease_owner = None
            run.lease_token = None
            run.lease_expires_at = None
            if run.kind == "report":
                report = db.query(models.AiReport).filter(models.AiReport.run_id == run.run_id).one_or_none()
                if report is None:
                    report = models.AiReport(
                        run_id=run.run_id,
                        device_id=run.device_id,
                        period=str(output.get("period") or "day"),
                        content=output,
                    )
                else:
                    report.content = output
                db.add(report)
            if run.kind == "patrol":
                policy = (
                    db.query(models.AutomationPolicy)
                    .filter(models.AutomationPolicy.device_id == run.device_id)
                    .one_or_none()
                )
                if policy is not None:
                    policy.last_model_run_at = now
                    db.add(policy)
            if run.kind == "strategy":
                policy = (
                    db.query(models.AutomationPolicy)
                    .filter(models.AutomationPolicy.device_id == run.device_id)
                    .one_or_none()
                )
                if policy is not None:
                    policy.last_strategy_run_at = now
                    db.add(policy)
            self._append_events(db, run, f"ai.run.{run.status}", run.status, {"output": output})
            db.commit()

    def fail(self, run_id: str, error: Exception, lease_token: str, *, retryable: bool = True) -> None:
        now = utcnow()
        with self.session_factory() as db:
            try:
                run = self._owned_run(db, run_id, lease_token)
            except RunLeaseLost:
                return
            if run.cancel_requested_at is not None:
                run.status = "cancelled"
                run.completed_at = now
                event_type = "ai.run.cancelled"
            elif retryable and run.attempt_count < (run.max_attempts or self.max_attempts):
                run.status = "queued"
                run.available_at = now + timedelta(seconds=min(30, 2 ** max(run.attempt_count, 1)))
                event_type = "ai.run.retry_scheduled"
            else:
                run.status = "failed"
                run.error_code = "ai_run_failed"
                run.error_message = str(error)[:2000]
                run.completed_at = now
                event_type = "ai.run.failed"
            run.lease_owner = None
            run.lease_token = None
            run.lease_expires_at = None
            self._append_events(db, run, event_type, run.status, {"error": str(error)[:500]})
            db.commit()

    def tool_started(self, run: dict[str, Any], call_id: str, name: str, arguments: dict[str, Any]) -> None:
        with self.session_factory() as db:
            self._owned_run(db, run["run_id"], run["lease_token"])
            call = db.query(models.AiToolCall).filter(models.AiToolCall.call_id == call_id).one_or_none()
            if call is None:
                call = models.AiToolCall(
                    call_id=call_id,
                    run_id=run["run_id"],
                    trace_id=run["trace_id"],
                    tool_name=name,
                    arguments=arguments,
                    status="started",
                )
            else:
                call.arguments = arguments
                call.status = "started"
                call.error_message = None
                call.completed_at = None
            db.add(call)
            self._append_trace(
                db,
                run["trace_id"],
                run["device_id"],
                "mcp",
                "mcp.tool.started",
                "started",
                {"call_id": call_id, "tool_name": name, "arguments": arguments},
            )
            db.commit()

    def tool_finished(
        self,
        run: dict[str, Any],
        call_id: str,
        result: dict[str, Any] | None,
        error: Exception | None,
    ) -> None:
        with self.session_factory() as db:
            self._owned_run(db, run["run_id"], run["lease_token"])
            call = db.query(models.AiToolCall).filter(models.AiToolCall.call_id == call_id).one()
            call.status = "failed" if error else "succeeded"
            call.result = result
            call.error_message = str(error) if error else None
            call.completed_at = utcnow()
            self._append_trace(
                db,
                call.trace_id,
                None,
                "mcp",
                "mcp.tool.finished",
                call.status,
                {
                    "call_id": call_id,
                    "tool_name": call.tool_name,
                    "result": result,
                    "error": str(error) if error else None,
                },
            )
            db.commit()

    def persist_report(self, run: dict[str, Any], period: str, output: dict[str, Any]) -> None:
        with self.session_factory() as db:
            self._owned_run(db, run["run_id"], run["lease_token"])
            report = db.query(models.AiReport).filter(models.AiReport.run_id == run["run_id"]).one_or_none()
            if report is None:
                report = models.AiReport(
                    run_id=run["run_id"], device_id=run["device_id"], period=period, content=output
                )
            else:
                report.period = period
                report.content = output
            db.add(report)
            db.commit()

    def acquire_runtime_lease(self, name: str, seconds: int) -> bool:
        now = utcnow()
        with self.session_factory() as db:
            query = db.query(models.RuntimeLease).filter(models.RuntimeLease.name == name)
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update()
            lease = query.one_or_none()
            if lease is not None and lease.owner != self.instance_id and lease.lease_expires_at > now:
                return False
            if lease is None:
                lease = models.RuntimeLease(name=name, owner=self.instance_id, lease_expires_at=now)
            lease.owner = self.instance_id
            lease.heartbeat_at = now
            lease.lease_expires_at = now + timedelta(seconds=seconds)
            db.add(lease)
            db.commit()
            return True

    @staticmethod
    def _run_dict(run: models.AiRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "device_id": run.device_id,
            "kind": run.kind,
            "trigger": run.trigger,
            "input": run.input_payload or {},
            "lease_token": run.lease_token or "",
        }

    def _owned_run(self, db: Session, run_id: str, lease_token: str) -> models.AiRun:
        now = utcnow()
        run = (
            db.query(models.AiRun)
            .filter(
                models.AiRun.run_id == run_id,
                models.AiRun.lease_owner == self.instance_id,
                models.AiRun.lease_token == lease_token,
                models.AiRun.status.in_(ACTIVE_RUN_STATUSES),
                models.AiRun.lease_expires_at >= now,
            )
            .one_or_none()
        )
        if run is None:
            raise RunLeaseLost(run_id)
        return run

    def _append_events(
        self,
        db: Session,
        run: models.AiRun,
        event_type: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "run_id": run.run_id,
            "kind": run.kind,
            "trigger": run.trigger,
            "status": status,
            **(detail or {}),
        }
        db.add(
            models.RealtimeEvent(
                event_id=f"evt-{uuid4().hex[:20]}",
                device_id=run.device_id,
                trace_id=run.trace_id,
                type="ai.run.status_changed",
                payload=payload,
            )
        )
        self._append_trace(db, run.trace_id, run.device_id, "ai", event_type, status, detail or {})

    @staticmethod
    def _append_trace(
        db: Session,
        trace_id: str,
        device_id: str | None,
        component: str,
        event_type: str,
        status: str | None,
        detail: dict[str, Any],
    ) -> None:
        db.add(
            models.TraceEvent(
                event_id=f"trace-{uuid4().hex[:20]}",
                trace_id=trace_id,
                device_id=device_id,
                component=component,
                event_type=event_type,
                status=status,
                detail=detail,
            )
        )
