from __future__ import annotations

from typing import Any, Protocol

from app.domain.commands import CommandRequest


class CommandRepository(Protocol):
    def device_status(self, device_id: str) -> str | None: ...

    def supported_commands(self, device_id: str) -> set[str] | None: ...

    def guard_command(self, request: CommandRequest) -> tuple[str, str] | None: ...

    def create_with_outbox(self, request: CommandRequest) -> dict[str, Any]: ...

    def get(self, device_id: str, command_id: str) -> dict[str, Any] | None: ...


class CommandNotifier(Protocol):
    async def command_changed(self, device_id: str, command: dict[str, Any]) -> None: ...
