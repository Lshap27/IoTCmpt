from __future__ import annotations

import asyncio
from typing import Any

from app.ports.automation_plans import AutomationPlanRepository


class AutomationPlanApplicationService:
    def __init__(self, repository: AutomationPlanRepository):
        self.repository = repository

    async def ensure_system_plan(self, device_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.ensure_system_plan, device_id)

    async def create_draft(
        self,
        device_id: str,
        source_prompt: str,
        spec: dict[str, Any],
        explanation: str,
        source_ai_run_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.repository.create_draft,
            device_id,
            source_prompt,
            spec,
            explanation,
            source_ai_run_id,
            trace_id,
        )

    async def list_plans(self, device_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.list_plans, device_id)

    async def get(self, device_id: str, plan_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.repository.get, device_id, plan_id)

    async def events(self, device_id: str, plan_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.events, device_id, plan_id, limit)

    async def transition(
        self, device_id: str, plan_id: str, action: str, *, replace_active: bool = False
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.transition, device_id, plan_id, action, replace_active)

    async def propose_strategy(
        self,
        device_id: str,
        run_id: str,
        plan_id: str | None,
        base_version: int | None,
        proposed_spec: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.repository.propose_strategy,
            device_id,
            run_id,
            plan_id,
            base_version,
            proposed_spec,
            summary,
        )

    async def list_strategies(self, device_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.repository.list_strategies, device_id)

    async def get_strategy(self, device_id: str, strategy_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.repository.get_strategy, device_id, strategy_id)

    async def resolve_strategy(self, device_id: str, strategy_id: str, action: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.repository.resolve_strategy, device_id, strategy_id, action)
