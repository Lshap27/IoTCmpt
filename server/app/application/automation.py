from __future__ import annotations

import asyncio
from typing import Any

from app.ports.automation import AiRunRepository, AutomationRepository


class AutomationApplicationService:
    def __init__(self, policies: AutomationRepository):
        self.policies = policies

    async def get_policy(self, device_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.policies.get_policy, device_id)

    async def update_policy(self, device_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self.policies.update_policy, device_id, changes)


class AiRunApplicationService:
    def __init__(self, runs: AiRunRepository):
        self.runs = runs

    async def create(self, device_id: str, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.runs.create, device_id, payload, trace_id)

    async def get(self, device_id: str, run_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.runs.get, device_id, run_id)

    async def list(
        self, device_id: str, *, kind: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.runs.list, device_id, kind, status, limit)

    async def cancel(self, device_id: str, run_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.runs.cancel, device_id, run_id)
