from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.db import models
from app.schemas import WebSocketEnvelope
from app.services.websocket import manager


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RealtimeEventWriter:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    async def command_changed(self, device_id: str, command: dict) -> None:
        with self.session_factory() as db:
            db.add(
                models.RealtimeEvent(
                    event_id=f"evt-{uuid4().hex[:20]}",
                    device_id=device_id,
                    trace_id=command.get("trace_id"),
                    type="command.status_changed",
                    payload=command,
                )
            )
            db.commit()


class RealtimeRelay:
    def __init__(self, session_factory: sessionmaker[Session], *, lease_seconds: int = 30):
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds
        self.owner = f"gateway-{uuid4().hex[:12]}"
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="realtime-relay")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            rows = await asyncio.to_thread(self._claim)
            for row in rows:
                envelope = WebSocketEnvelope(
                    type=row["type"],
                    device_id=row["device_id"],
                    trace_id=row["trace_id"],
                    payload=row["payload"],
                )
                await manager.broadcast(row["device_id"], envelope.model_dump(mode="json"))
                await asyncio.to_thread(self._finish, row["id"])
            await asyncio.sleep(0.2 if rows else 0.5)

    def _claim(self) -> list[dict]:
        now = utcnow()
        with self.session_factory() as db:
            query = (
                db.query(models.RealtimeEvent)
                .filter(
                    (models.RealtimeEvent.status == "pending")
                    | ((models.RealtimeEvent.status == "delivering") & (models.RealtimeEvent.lease_expires_at < now))
                )
                .order_by(models.RealtimeEvent.created_at.asc())
                .limit(50)
            )
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = query.all()
            result = []
            for row in rows:
                row.status = "delivering"
                row.attempts += 1
                row.lease_owner = self.owner
                row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                result.append(
                    {
                        "id": row.id,
                        "type": row.type,
                        "device_id": row.device_id,
                        "trace_id": row.trace_id,
                        "payload": row.payload,
                    }
                )
            db.commit()
            return result

    def _finish(self, row_id: int) -> None:
        with self.session_factory() as db:
            row = db.get(models.RealtimeEvent, row_id)
            if row is None or row.lease_owner != self.owner:
                return
            row.status = "delivered"
            row.delivered_at = utcnow()
            row.lease_owner = None
            row.lease_expires_at = None
            if row.trace_id:
                db.add(
                    models.TraceEvent(
                        event_id=f"trace-{uuid4().hex[:20]}",
                        trace_id=row.trace_id,
                        device_id=row.device_id,
                        component="websocket",
                        event_type="websocket.delivered",
                        status="delivered",
                        detail={"type": row.type, "event_id": row.event_id},
                    )
                )
            db.commit()
