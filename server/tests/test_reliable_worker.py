from __future__ import annotations

from datetime import timedelta

from app.adapters.job_store import SqlAlchemyJobStore, utcnow
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
    assert first.claim_next()["run_id"] == "run-reliable"
    assert second.claim_next() is None

    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-reliable").one()
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    assert second.recover_expired() == 1
    with SessionLocal() as db:
        run = db.query(models.AiRun).filter(models.AiRun.run_id == "run-reliable").one()
        assert run.status == "queued"
        assert run.attempt_count == 1
        assert run.lease_owner is None


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
