from __future__ import annotations

from typing import Any, Protocol


class AutomationPlanRepository(Protocol):
    def ensure_system_plan(self, device_id: str) -> dict[str, Any]: ...

    def create_draft(
        self,
        device_id: str,
        source_prompt: str,
        spec: dict[str, Any],
        explanation: str,
        source_ai_run_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def list_plans(self, device_id: str) -> list[dict[str, Any]]: ...

    def get(self, device_id: str, plan_id: str) -> dict[str, Any] | None: ...

    def events(self, device_id: str, plan_id: str, limit: int) -> list[dict[str, Any]]: ...

    def transition(self, device_id: str, plan_id: str, action: str, replace_active: bool = False) -> dict[str, Any]: ...

    def propose_strategy(
        self,
        device_id: str,
        run_id: str,
        plan_id: str | None,
        base_version: int | None,
        proposed_spec: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]: ...

    def list_strategies(self, device_id: str) -> list[dict[str, Any]]: ...

    def get_strategy(self, device_id: str, strategy_id: str) -> dict[str, Any] | None: ...

    def resolve_strategy(self, device_id: str, strategy_id: str, action: str) -> dict[str, Any]: ...
