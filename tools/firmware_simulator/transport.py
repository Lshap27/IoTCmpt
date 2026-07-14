from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiomqtt
import httpx
from aiomqtt.client import Will

DEFAULT_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwc"
    "KDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAgACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol"
    "JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAA"
    "AAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR"
    "ChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX"
    "mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEA"
    "PwB1FFFfUHz4UUUUAFFFFABRRRQB/9k="
)


class EnvelopeEncoder:
    def __init__(self, device_id: str, boot_id: str):
        self.device_id = device_id
        self.boot_id = boot_id
        self.sequence = 0

    def encode(self, payload: dict[str, Any], *, trace_id: str | None = None) -> dict[str, Any]:
        self.sequence += 1
        return {
            "schema_version": "2.0",
            "message_id": str(uuid.uuid4()),
            "trace_id": trace_id or str(uuid.uuid4()),
            "device_id": self.device_id,
            "occurred_at": datetime.now(UTC).isoformat(),
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "payload": payload,
        }


def mqtt_client(host: str, port: int, device_id: str, offline_payload: dict[str, Any]) -> aiomqtt.Client:
    return aiomqtt.Client(
        host,
        port=port,
        identifier=f"firmware-sim-{device_id}",
        will=Will(
            f"devices/{device_id}/status",
            json.dumps(offline_payload, ensure_ascii=False),
            qos=1,
            retain=True,
        ),
    )


async def upload_image(api_base: str, device_id: str, image_path: str | None) -> str:
    content = Path(image_path).read_bytes() if image_path else DEFAULT_JPEG
    url = f"{api_base.rstrip('/')}/api/v1/devices/{device_id}/images"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            url,
            files={"file": ("firmware-simulator.jpg", content, "image/jpeg")},
        )
        response.raise_for_status()
        body = response.json()
        return str(body.get("url") or url)
