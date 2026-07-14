from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Tool


class McpToolClient:
    def __init__(self, base_url: str, internal_token: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def session(self, trace_id: str) -> AsyncIterator[ClientSession]:
        headers = {"x-aiot-internal-token": self.internal_token, "x-trace-id": trace_id}
        async with (
            httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as http_client,
            streamable_http_client(
                f"{self.base_url}/mcp/",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _),
            ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
            ) as session,
        ):
            await session.initialize()
            yield session

    @staticmethod
    def openai_tools(tools: list[Tool], *, allow_control: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for tool in tools:
            if not allow_control and tool.name in {"device_execute_command", "device_create_notification"}:
                continue
            rows.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or tool.name,
                        "parameters": tool.inputSchema,
                    },
                }
            )
        return rows

    @staticmethod
    def result_payload(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        texts = [getattr(item, "text", "") for item in result.content if getattr(item, "type", "") == "text"]
        joined = "\n".join(text for text in texts if text)
        try:
            parsed = json.loads(joined)
        except (json.JSONDecodeError, TypeError):
            return {"ok": not result.isError, "data": joined, "error": None if not result.isError else joined}
        return parsed if isinstance(parsed, dict) else {"ok": not result.isError, "data": parsed, "error": None}
