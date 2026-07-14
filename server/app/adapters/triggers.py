from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db import models

EVENT_TRIGGER_TYPES = {"smoke.detected", "air_quality.alert", "device.fault", "posture.sedentary"}
ACTIVE_STATUSES = {"queued", "running", "waiting_model", "calling_tool", "waiting_device"}


def enqueue_event_run(
    session_factory: sessionmaker[Session],
    settings: Settings,
    device_id: str,
    event_type: str,
) -> None:
    if event_type not in EVENT_TRIGGER_TYPES:
        return
    with session_factory() as db:
        policy = db.query(models.AutomationPolicy).filter(models.AutomationPolicy.device_id == device_id).one_or_none()
        if policy is None or not policy.enabled or not policy.event_trigger_enabled:
            return
        if event_type == "posture.sedentary" and not policy.sedentary_trigger_enabled:
            return
        existing = (
            db.query(models.AiRun)
            .filter(
                models.AiRun.device_id == device_id,
                models.AiRun.trigger == "event",
                models.AiRun.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )
        if existing is not None:
            existing.input_payload = {
                **(existing.input_payload or {}),
                "coalesced_triggers": int((existing.input_payload or {}).get("coalesced_triggers", 0)) + 1,
                "latest_event_type": event_type,
            }
            db.commit()
            return
        now = datetime.now(UTC).replace(tzinfo=None)
        run = models.AiRun(
            run_id=f"run-{uuid4().hex[:16]}",
            trace_id=f"trace-{uuid4().hex[:16]}",
            device_id=device_id,
            kind="decision",
            trigger="event",
            status="queued",
            available_at=now,
            max_attempts=settings.ai_worker_max_attempts,
            input_payload={"kind": "decision", "trigger": "event", "goal": f"处理事件 {event_type}"},
        )
        db.add(run)
        db.add(
            models.TraceEvent(
                event_id=f"trace-{uuid4().hex[:20]}",
                trace_id=run.trace_id,
                device_id=device_id,
                component="mqtt",
                event_type="ai.run.queued_from_event",
                status="queued",
                detail={"run_id": run.run_id, "event_type": event_type},
            )
        )
        db.commit()
