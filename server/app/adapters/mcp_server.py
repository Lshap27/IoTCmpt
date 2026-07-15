from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.domain.commands import CommandRejected, CommandRequest
from app.schemas_v1 import AutomationPlanSpecV1In
from app.services.voice_commands import submit_speech

MCP_SCOPES: ContextVar[frozenset[str]] = ContextVar("mcp_scopes", default=frozenset())
MCP_TRACE_ID: ContextVar[str] = ContextVar("mcp_trace_id", default="")
MCP_INTERNAL: ContextVar[bool] = ContextVar("mcp_internal", default=False)


def tool_result(*, data: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": error is None, "trace_id": MCP_TRACE_ID.get(), "data": data, "error": error}


def require_scope(scope: str) -> None:
    if scope not in MCP_SCOPES.get():
        raise PermissionError(f"MCP token requires {scope} scope")


class McpBearerMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, internal_token: str):
        self.app = app
        self.settings = settings
        self.internal_token = internal_token
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        internal = headers.get(b"x-aiot-internal-token", b"").decode("utf-8")
        if internal and self.internal_token and secrets.compare_digest(internal, self.internal_token):
            scopes = frozenset({"mcp:read", "mcp:control"})
            token = "internal"
        else:
            if not self.settings.mcp_enabled:
                await JSONResponse({"detail": "MCP is disabled"}, status_code=503)(scope, receive, send)
                return
            token = ""
            scopes = frozenset()
        origin = headers.get(b"origin", b"").decode("utf-8")
        host_header = headers.get(b"host", b"").decode("utf-8")
        host = urlsplit(f"//{host_header}").hostname or ""
        allowed_hosts = {urlsplit(f"//{item}").hostname or item for item in self.settings.mcp_allowed_hosts}
        if token != "internal" and host not in allowed_hosts:
            await JSONResponse({"detail": "MCP host is not allowed"}, status_code=421)(scope, receive, send)
            return
        if token != "internal" and origin and origin not in self.settings.mcp_allowed_origins:
            await JSONResponse({"detail": "MCP origin is not allowed"}, status_code=403)(scope, receive, send)
            return
        if token != "internal":
            authorization = headers.get(b"authorization", b"").decode("utf-8")
            token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
            if token and secrets.compare_digest(token, self.settings.mcp_control_token):
                scopes = frozenset({"mcp:read", "mcp:control"})
            elif token and secrets.compare_digest(token, self.settings.mcp_read_token):
                scopes = frozenset({"mcp:read"})
            else:
                await JSONResponse(
                    {"detail": "A valid MCP bearer token is required"},
                    status_code=401,
                    headers={"www-authenticate": "Bearer"},
                )(scope, receive, send)
                return
        if token != "internal":
            now = time.monotonic()
            bucket = self._requests[token]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= self.settings.mcp_rate_limit_per_minute:
                await JSONResponse({"detail": "MCP rate limit exceeded"}, status_code=429)(scope, receive, send)
                return
            bucket.append(now)
        trace_id = headers.get(b"x-trace-id", b"").decode("utf-8")
        if not trace_id:
            from uuid import uuid4

            trace_id = f"trace-{uuid4().hex[:16]}"
        scope_token = MCP_SCOPES.set(scopes)
        trace_token = MCP_TRACE_ID.set(trace_id)
        internal_context = MCP_INTERNAL.set(token == "internal")
        try:
            await self.app(scope, receive, send)
        finally:
            MCP_SCOPES.reset(scope_token)
            MCP_TRACE_ID.reset(trace_token)
            MCP_INTERNAL.reset(internal_context)


def create_mcp_server(app: Any, settings: Settings, internal_token: str) -> tuple[FastMCP, Starlette, ASGIApp]:
    server = FastMCP(
        "IoTCmpt Device Tools",
        instructions="Read device state and execute AI-safe ESP32-S3 commands through the trusted gateway.",
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            # External Host/Origin checks live in McpBearerMiddleware so the
            # authenticated Docker-internal worker can bypass only those two
            # network-edge checks. Tool scopes and command policy still apply.
            enable_dns_rebinding_protection=False,
        ),
    )

    @server.tool(name="device_list", structured_output=True)
    async def device_list() -> dict[str, Any]:
        """List devices known to this gateway."""
        require_scope("mcp:read")
        return tool_result(data=await app.state.device_queries.list_devices())

    @server.tool(name="device_get_snapshot", structured_output=True)
    async def device_get_snapshot(device_id: str) -> dict[str, Any]:
        """Return the latest telemetry, reported state, image, pose, and command for one device."""
        require_scope("mcp:read")
        return tool_result(data=await app.state.device_queries.snapshot(device_id))

    @server.tool(name="device_get_history", structured_output=True)
    async def device_get_history(
        device_id: str,
        limit: int = 50,
        start_at: str | None = None,
        end_at: str | None = None,
        bucket_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Return recent telemetry points for one device, newest first."""
        require_scope("mcp:read")
        from datetime import UTC, datetime

        if bucket_seconds is not None and not 10 <= bucket_seconds <= 86400:
            return tool_result(error={"code": "invalid_parameter", "message": "bucket_seconds must be 10..86400"})
        try:
            start_value = datetime.fromisoformat(start_at.replace("Z", "+00:00")) if start_at else None
            end_value = datetime.fromisoformat(end_at.replace("Z", "+00:00")) if end_at else None
            start = start_value.astimezone(UTC).replace(tzinfo=None) if start_value else None
            end = end_value.astimezone(UTC).replace(tzinfo=None) if end_value else None
        except ValueError:
            return tool_result(error={"code": "invalid_parameter", "message": "invalid ISO timestamp"})
        data = await app.state.device_queries.history(
            device_id,
            limit=max(1, min(limit, 2000)),
            start_at=start,
            end_at=end,
            bucket_seconds=bucket_seconds,
        )
        return tool_result(data={"points": data, "bucket_seconds": bucket_seconds})

    @server.tool(name="device_list_events", structured_output=True)
    async def device_list_events(device_id: str, limit: int = 50) -> dict[str, Any]:
        """Return recent device events."""
        require_scope("mcp:read")
        return tool_result(data=await app.state.device_queries.events(device_id, limit=max(1, min(limit, 500))))

    @server.tool(name="device_get_capabilities", structured_output=True)
    async def device_get_capabilities(device_id: str) -> dict[str, Any]:
        """Return the command capabilities advertised by a device."""
        require_scope("mcp:read")
        capability = await app.state.device_queries.capabilities(device_id)
        if capability is None:
            return tool_result(error={"code": "capabilities_unknown", "message": "device has not advertised v2"})
        return tool_result(data=capability)

    @server.tool(name="device_execute_command", structured_output=True)
    async def device_execute_command(
        device_id: str,
        command_type: str,
        parameter: dict[str, Any] | None = None,
        reason: str = "MCP tool call",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute an AI-safe device command through the gateway command application."""
        require_scope("mcp:control")
        try:
            command = await app.state.command_application.submit(
                CommandRequest(
                    device_id=device_id,
                    type=command_type,
                    parameter=parameter or {},
                    source="ai" if MCP_INTERNAL.get() else "external_mcp",
                    reason=reason,
                    trace_id=MCP_TRACE_ID.get(),
                    idempotency_key=idempotency_key,
                ),
                ai_restricted=MCP_INTERNAL.get(),
            )
        except CommandRejected as exc:
            return tool_result(error={"code": exc.error_code, "message": str(exc)})
        return tool_result(data=command)

    @server.tool(name="device_get_command", structured_output=True)
    async def device_get_command(device_id: str, command_id: str) -> dict[str, Any]:
        """Read the current lifecycle state of a command."""
        require_scope("mcp:read")
        command = await app.state.command_application.get(device_id, command_id)
        if command is None:
            return tool_result(error={"code": "not_found", "message": "command not found"})
        return tool_result(data=command)

    @server.tool(name="device_speak", structured_output=True)
    async def device_speak(
        device_id: str,
        text: str,
        reason: str = "MCP speech request",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Speak plain text through the device using validated GB2312 conversion."""
        require_scope("mcp:control")
        try:
            command = await submit_speech(
                app.state.command_application,
                device_id=device_id,
                text=text,
                source="ai" if MCP_INTERNAL.get() else "external_mcp",
                reason=reason,
                trace_id=MCP_TRACE_ID.get(),
                idempotency_key=idempotency_key,
                ai_restricted=True,
            )
        except CommandRejected as exc:
            return tool_result(error={"code": exc.error_code, "message": str(exc)})
        return tool_result(data=command)

    @server.tool(name="device_create_notification", structured_output=True)
    async def device_create_notification(device_id: str, content: str) -> dict[str, Any]:
        """Create a persisted text notification for a device."""
        require_scope("mcp:control")
        return tool_result(data=await app.state.device_queries.create_notification(device_id, content))

    @server.tool(name="automation_plan_list", structured_output=True)
    async def automation_plan_list(device_id: str) -> dict[str, Any]:
        """List deterministic automation plans and their current immutable versions."""
        require_scope("mcp:read")
        return tool_result(data=await app.state.automation_plan_application.list_plans(device_id))

    @server.tool(name="automation_plan_get", structured_output=True)
    async def automation_plan_get(device_id: str, plan_id: str) -> dict[str, Any]:
        """Read one automation plan and its current validated DSL."""
        require_scope("mcp:read")
        plan = await app.state.automation_plan_application.get(device_id, plan_id)
        if plan is None:
            return tool_result(error={"code": "not_found", "message": "automation plan not found"})
        return tool_result(data=plan)

    @server.tool(name="automation_plan_events", structured_output=True)
    async def automation_plan_events(device_id: str, plan_id: str, limit: int = 100) -> dict[str, Any]:
        """Read recent deterministic automation plan audit events."""
        require_scope("mcp:read")
        return tool_result(
            data=await app.state.automation_plan_application.events(
                device_id,
                plan_id,
                max(1, min(limit, 500)),
            )
        )

    @server.tool(name="automation_strategy_get", structured_output=True)
    async def automation_strategy_get(device_id: str, strategy_id: str) -> dict[str, Any]:
        """Read one AI strategy candidate and its server-computed structural diff."""
        require_scope("mcp:read")
        strategy = await app.state.automation_plan_application.get_strategy(device_id, strategy_id)
        if strategy is None:
            return tool_result(error={"code": "not_found", "message": "AI strategy not found"})
        return tool_result(data=strategy)

    @server.tool(name="automation_plan_create_draft", structured_output=True)
    async def automation_plan_create_draft(
        device_id: str,
        run_id: str,
        source_prompt: str,
        spec: AutomationPlanSpecV1In,
        explanation: str,
    ) -> dict[str, Any]:
        """Internal-only: validate and persist an immutable AutomationPlanSpec v1 draft."""
        require_scope("mcp:control")
        if not MCP_INTERNAL.get():
            raise PermissionError("automation plan drafts are internal AI Worker operations")
        try:
            plan = await app.state.automation_plan_application.create_draft(
                device_id,
                source_prompt,
                spec.model_dump(mode="json", exclude_none=True),
                explanation,
                run_id,
                MCP_TRACE_ID.get(),
            )
        except ValueError as exc:
            return tool_result(error={"code": "invalid_automation_plan", "message": str(exc)})
        return tool_result(data=plan)

    @server.tool(name="automation_strategy_propose", structured_output=True)
    async def automation_strategy_propose(
        device_id: str,
        run_id: str,
        proposed_spec: AutomationPlanSpecV1In,
        summary: str,
        plan_id: str | None = None,
        base_version: int | None = None,
    ) -> dict[str, Any]:
        """Internal-only: validate and persist a strategy candidate without activating it."""
        require_scope("mcp:control")
        if not MCP_INTERNAL.get():
            raise PermissionError("strategy proposals are internal AI Worker operations")
        try:
            strategy = await app.state.automation_plan_application.propose_strategy(
                device_id,
                run_id,
                plan_id,
                base_version,
                proposed_spec.model_dump(mode="json", exclude_none=True),
                summary,
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            return tool_result(error={"code": "invalid_strategy", "message": str(exc)})
        return tool_result(data=strategy)

    mcp_app = server.streamable_http_app()
    return server, mcp_app, McpBearerMiddleware(mcp_app, settings, internal_token)
