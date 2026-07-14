from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class DeviceQueryRepository(Protocol):
    def list_devices(self) -> list[dict[str, Any]]: ...

    def snapshot(self, device_id: str) -> dict[str, Any]: ...

    def history(
        self,
        device_id: str,
        *,
        limit: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        bucket_seconds: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def events(self, device_id: str, *, limit: int) -> list[dict[str, Any]]: ...

    def capabilities(self, device_id: str) -> dict[str, Any] | None: ...

    def notifications(self, device_id: str, *, limit: int) -> list[dict[str, Any]]: ...

    def create_notification(self, device_id: str, content: str) -> dict[str, Any]: ...

    def link_notification_command(self, notification_id: int, command_id: str) -> dict[str, Any]: ...

    def diagnostics_overview(self) -> dict[str, Any]: ...

    def trace_timeline(self, trace_id: str) -> dict[str, Any]: ...
