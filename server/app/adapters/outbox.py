from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence import serialize_v2_command
from app.db import models
from app.ports.commands import CommandNotifier
from app.services.mqtt import MqttGateway

LOGGER = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        mqtt: MqttGateway,
        notifier: CommandNotifier,
        ack_timeout_seconds: float,
        lease_seconds: int = 30,
    ):
        self.session_factory = session_factory
        self.mqtt = mqtt
        self.notifier = notifier
        self.ack_timeout_seconds = ack_timeout_seconds
        self.lease_seconds = lease_seconds
        self.owner = f"outbox-{uuid4().hex[:12]}"
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="command-outbox")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.dispatch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("command outbox dispatch failed")
            await asyncio.sleep(0.5)

    async def dispatch_once(self) -> int:
        changed = await asyncio.to_thread(self._expire_and_timeout)
        for command in changed:
            await self.notifier.command_changed(command["device_id"], command)
        rows = await asyncio.to_thread(self._claim_pending)
        published = 0
        for row_id, topic, payload, qos in rows:
            ok = await self.mqtt.publish_json(topic, payload, qos=qos)
            await asyncio.to_thread(self._record_attempt, row_id, ok)
            published += int(ok)
        return published

    def _expire_and_timeout(self) -> list[dict]:
        now = utcnow()
        timeout_before = now - timedelta(seconds=self.ack_timeout_seconds)
        changed: list[dict] = []
        with self.session_factory() as db:
            expiring = (
                db.query(models.Command)
                .filter(
                    models.Command.status.in_(["queued", "published"]),
                    models.Command.expires_at.is_not(None),
                    models.Command.expires_at <= now,
                )
                .all()
            )
            timing_out = (
                db.query(models.Command)
                .filter(
                    ((models.Command.status == "published") & (models.Command.published_at <= timeout_before))
                    | ((models.Command.status == "accepted") & (models.Command.accepted_at <= timeout_before))
                )
                .all()
            )
            for command, terminal, error_code in [
                *((row, "expired", "expired") for row in expiring),
                *((row, "timed_out", "timeout") for row in timing_out if row not in expiring),
            ]:
                previous = command.status
                command.status = terminal
                command.error_code = error_code
                command.executed_at = now
                db.add(
                    models.CommandEvent(
                        command_id=command.command_id,
                        trace_id=command.trace_id,
                        from_status=previous,
                        to_status=terminal,
                        error_code=error_code,
                    )
                )
                if terminal == "expired":
                    rows = (
                        db.query(models.OutboxMessage)
                        .filter(
                            models.OutboxMessage.command_id == command.command_id,
                            models.OutboxMessage.status.in_(["pending", "retry"]),
                        )
                        .all()
                    )
                    for row in rows:
                        row.status = "cancelled"
                        row.last_error = "expired"
                        db.add(row)
                db.add(command)
                changed.append(serialize_v2_command(command))
            db.commit()
        return changed

    def _claim_pending(self) -> list[tuple[int, str, dict, int]]:
        now = utcnow()
        with self.session_factory() as db:
            query = (
                db.query(models.OutboxMessage)
                .filter(
                    (
                        models.OutboxMessage.status.in_(["pending", "retry"])
                        & (
                            (models.OutboxMessage.next_attempt_at.is_(None))
                            | (models.OutboxMessage.next_attempt_at <= now)
                        )
                    )
                    | ((models.OutboxMessage.status == "publishing") & (models.OutboxMessage.lease_expires_at < now)),
                )
                .order_by(models.OutboxMessage.created_at.asc())
                .limit(20)
            )
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = query.all()
            for row in rows:
                row.status = "publishing"
                row.lease_owner = self.owner
                row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            db.commit()
            return [(row.id, row.topic, row.payload, row.qos) for row in rows]

    def _record_attempt(self, row_id: int, ok: bool) -> None:
        with self.session_factory() as db:
            row = db.get(models.OutboxMessage, row_id)
            if row is None or row.status == "published" or row.lease_owner != self.owner:
                return
            row.attempts += 1
            command = db.query(models.Command).filter(models.Command.command_id == row.command_id).one()
            command.attempt_count = row.attempts
            if ok:
                now = utcnow()
                previous = command.status
                row.status = "published"
                row.published_at = now
                row.last_error = None
                command.published_at = now
                if command.status == "queued":
                    command.status = "published"
                db.add(
                    models.CommandEvent(
                        command_id=command.command_id,
                        trace_id=command.trace_id,
                        from_status=previous,
                        to_status=command.status,
                    )
                )
                db.add(
                    models.TraceEvent(
                        event_id=f"trace-{uuid4().hex[:20]}",
                        trace_id=command.trace_id,
                        device_id=command.device_id,
                        component="mqtt",
                        event_type="mqtt.command.published",
                        status="published",
                        detail={"command_id": command.command_id, "attempt": row.attempts},
                    )
                )
            else:
                if row.attempts >= row.max_attempts:
                    row.status = "failed"
                    row.last_error = "max_attempts_exceeded"
                    previous = command.status
                    command.status = "failed"
                    command.error_code = "transport_error"
                    command.executed_at = utcnow()
                    db.add(
                        models.CommandEvent(
                            command_id=command.command_id,
                            trace_id=command.trace_id,
                            from_status=previous,
                            to_status="failed",
                            error_code="transport_error",
                        )
                    )
                else:
                    row.status = "retry"
                    row.last_error = "mqtt_unavailable"
                    row.next_attempt_at = utcnow() + timedelta(seconds=min(30, 2 ** min(row.attempts, 4)))
            row.lease_owner = None
            row.lease_expires_at = None
            db.add_all([row, command])
            db.commit()
