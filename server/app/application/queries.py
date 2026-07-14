from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.ports.queries import DeviceQueryRepository


class DeviceQueryApplicationService:
    def __init__(self, repository: DeviceQueryRepository):
        self.repository = repository

    async def list_devices(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.list_devices)

    async def snapshot(self, device_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.snapshot, device_id)

    async def history(
        self,
        device_id: str,
        *,
        limit: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        bucket_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.repository.history,
            device_id,
            limit=limit,
            start_at=start_at,
            end_at=end_at,
            bucket_seconds=bucket_seconds,
        )

    async def events(self, device_id: str, *, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.events, device_id, limit=limit)

    async def capabilities(self, device_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.repository.capabilities, device_id)

    async def notifications(self, device_id: str, *, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.notifications, device_id, limit=limit)

    async def create_notification(self, device_id: str, content: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.create_notification, device_id, content)

    async def link_notification_command(self, notification_id: int, command_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.link_notification_command, notification_id, command_id)

    async def diagnostics_overview(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.diagnostics_overview)

    async def trace_timeline(self, trace_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.trace_timeline, trace_id)
