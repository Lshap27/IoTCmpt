from __future__ import annotations

from typing import Any

from app.schemas import WebSocketEnvelope
from app.services.websocket import manager


class WebSocketCommandNotifier:
    async def command_changed(self, device_id: str, command: dict[str, Any]) -> None:
        envelope = WebSocketEnvelope(type="command.status_changed", device_id=device_id, payload=command)
        await manager.broadcast(device_id, envelope.model_dump(mode="json"))
