from __future__ import annotations

from datetime import timedelta

import pytest

from app.adapters.job_store import RunCancelled, RunLeaseLost, SqlAlchemyJobStore, utcnow
from app.db import models
from app.services.commands import ensure_device


def _queued_run(run_id: str = "run-reliable") -> models.AiRun:
    return models.AiRun(
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        device_id="worker-device",
        kind="decision",
        trigger="manual",
        status="queued",
        available_at=utcnow(),
        max_attempts=3,
        input_payload={"kind": "decision"},
    )


def test_job_claim_is_exclusive_and_expired_lease_recovers(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        ensure_device(db, "worker-device")
        db.add(_queued_run())
        db.commit()

    first = SqlAlchemyJobStore(SessionLocal, "worker-a", lease_seconds=30)
    second = SqlAlchemyJobStore(SessionLocal, "worker-b", lease_seconds=30)
    first_claim = first.claim_next()
    assert first_claim["run_id"] == "run-reliable"
    assert first_claim["lease_token"]
    assert second.claim_next() is None

    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-reliable").one()
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    assert second.recover_expired() == 1
    second_claim = second.claim_next()
    assert second_claim is None  # recovery backoff prevents an immediate hot loop
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-reliable").one()
        run.available_at = utcnow() - timedelta(seconds=1)
        db.commit()
    second_claim = second.claim_next()
    assert second_claim["lease_token"] != first_claim["lease_token"]
    with pytest.raises(RunLeaseLost):
        first.transition("run-reliable", "calling_tool", first_claim["lease_token"])
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-reliable").one()
        assert run.status == "running"
        assert run.attempt_count == 2
        assert run.lease_owner == "worker-b"


def test_job_store_fails_after_max_lost_attempts(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        ensure_device(db, "worker-device")
        run = _queued_run("run-exhausted")
        run.status = "running"
        run.attempt_count = 3
        run.lease_owner = "dead-worker"
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.add(run)
        db.commit()

    store = SqlAlchemyJobStore(SessionLocal, "worker-c", lease_seconds=30, max_attempts=3)
    assert store.recover_expired() == 1
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-exhausted").one()
        assert run.status == "failed"
        assert run.error_code == "worker_lost"


def test_cancel_request_wins_over_worker_completion(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        ensure_device(db, "worker-device")
        db.add(_queued_run("run-cancel-race"))
        db.commit()

    store = SqlAlchemyJobStore(SessionLocal, "worker-a", lease_seconds=30)
    claim = store.claim_next()
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-cancel-race").one()
        run.cancel_requested_at = utcnow()
        db.commit()

    with pytest.raises(RunCancelled):
        store.complete("run-cancel-race", {"summary": "stale"}, "mock", claim["lease_token"])
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-cancel-race").one()
        assert run.status == "cancelled"
        assert run.output_payload is None


def test_tool_call_and_report_persistence_are_idempotent(client):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        ensure_device(db, "worker-device")
        run = _queued_run("run-idempotent")
        run.kind = "report"
        db.add(run)
        db.commit()

    store = SqlAlchemyJobStore(SessionLocal, "worker-a", lease_seconds=30)
    claim = store.claim_next()
    store.tool_started(claim, "call-stable", "device_get_history", {"device_id": "worker-device"})
    store.tool_started(claim, "call-stable", "device_get_history", {"device_id": "worker-device"})
    store.persist_report(claim, "day", {"period": "day", "summary": "one"})
    store.persist_report(claim, "day", {"period": "day", "summary": "two"})
    with SessionLocal() as db:
        assert db.query(models.AiToolCall).filter(models.AiToolCall.call_id == "call-stable").count() == 1
        reports = db.query(models.AiReport).filter(models.AiReport.run_id == "run-idempotent").all()
        assert len(reports) == 1
        assert reports[0].content["summary"] == "two"
