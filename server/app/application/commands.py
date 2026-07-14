from __future__ import annotations

import asyncio
from typing import Any

from app.domain.commands import CommandRejected, CommandRequest, validate_command
from app.ports.commands import CommandNotifier, CommandRepository


class CommandApplicationService:
    def __init__(self, repository: CommandRepository, notifier: CommandNotifier):
        self.repository = repository
        self.notifier = notifier

    async def submit(self, request: CommandRequest, *, ai_restricted: bool = False) -> dict[str, Any]:
        validate_command(request, ai_restricted=ai_restricted)
        if ai_restricted:
            status = await asyncio.to_thread(self.repository.device_status, request.device_id)
            if status != "online":
                raise CommandRejected("device_offline", "device is not online")
        supported = await asyncio.to_thread(self.repository.supported_commands, request.device_id)
        if ai_restricted and supported is None:
            raise CommandRejected("unsupported_command", "device capabilities are unknown")
        if supported is not None and request.type not in supported:
            raise CommandRejected("unsupported_command", f"device does not advertise {request.type}")
        if ai_restricted:
            denied = await asyncio.to_thread(self.repository.guard_command, request)
            if denied is not None:
                raise CommandRejected(*denied)
        command = await asyncio.to_thread(self.repository.create_with_outbox, request)
        await self.notifier.command_changed(request.device_id, command)
        return command

    async def get(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.repository.get, device_id, command_id)
