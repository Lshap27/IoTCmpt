from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[device_id].add(websocket)

    def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        self._connections[device_id].discard(websocket)

    async def broadcast(self, device_id: str, envelope: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self._connections.get(device_id, set())):
            try:
                await websocket.send_json(envelope)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(device_id, websocket)


manager = WebSocketManager()
