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
            except Exception:
                # 半开/已断开的连接在 uvicorn+starlette 下抛 WebSocketDisconnect（非 RuntimeError）。
                # 广播绝不能因个别死连接失败：踢掉它，继续发给其余客户端。
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(device_id, websocket)


manager = WebSocketManager()
