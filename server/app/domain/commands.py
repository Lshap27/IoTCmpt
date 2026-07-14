from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.generated.command_catalog import AI_COMMAND_NAMES, COMMAND_CATALOG, COMMAND_NAMES

CommandSource = Literal["frontend", "ai", "external_mcp", "rule"]
CommandStatus = Literal[
    "created",
    "queued",
    "published",
    "accepted",
    "executed",
    "rejected",
    "failed",
    "expired",
    "timed_out",
]
TERMINAL_COMMAND_STATUSES = frozenset({"executed", "rejected", "failed", "expired", "timed_out"})


class CommandRejected(ValueError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class CommandRequest:
    device_id: str
    type: str
    parameter: dict[str, Any] = field(default_factory=dict)
    source: CommandSource = "frontend"
    reason: str = ""
    trace_id: str = ""
    idempotency_key: str | None = None
    expires_at: datetime | None = None


def validate_command(request: CommandRequest, *, ai_restricted: bool = False) -> None:
    if request.expires_at is not None:
        expires_at = request.expires_at
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
        if expires_at <= datetime.now(UTC).replace(tzinfo=None):
            raise CommandRejected("expired", "command expiry must be in the future")
    if request.type not in COMMAND_NAMES:
        raise CommandRejected("unsupported_command", f"unsupported command: {request.type}")
    if ai_restricted and request.type not in AI_COMMAND_NAMES:
        raise CommandRejected("policy_denied", f"command is not available to AI: {request.type}")
    allowed_sources = set(COMMAND_CATALOG[request.type].get("allowed_sources", ()))
    if request.source not in allowed_sources:
        raise CommandRejected("policy_denied", f"{request.type} is not available to source {request.source}")
    if not isinstance(request.parameter, dict):
        raise CommandRejected("invalid_parameter", "parameter must be an object")
    _validate_parameter(request.type, request.parameter)


def _validate_parameter(command_type: str, parameter: dict[str, Any]) -> None:
    schema = COMMAND_CATALOG[command_type]["parameter_schema"]
    allowed = set(schema.get("properties", {}))
    if schema.get("additionalProperties") is False:
        unknown = set(parameter) - allowed
        if unknown:
            raise CommandRejected("invalid_parameter", f"unknown parameter fields: {sorted(unknown)}")
    for name in schema.get("required", []):
        if name not in parameter:
            raise CommandRejected("invalid_parameter", f"missing parameter: {name}")
    if command_type == "control.set_priority" and parameter.get("priority") not in {"manual_first", "auto_first"}:
        raise CommandRejected("invalid_parameter", "priority must be manual_first or auto_first")
    if command_type == "alarm.silence" and "duration_seconds" in parameter:
        value = parameter["duration_seconds"]
        if not isinstance(value, int) or isinstance(value, bool) or not 10 <= value <= 600:
            raise CommandRejected("invalid_parameter", "duration_seconds must be an integer from 10 to 600")
    if command_type == "display.message":
        text = parameter.get("text")
        limit = 120
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            raise CommandRejected("invalid_parameter", f"text must contain 1 to {limit} characters")
    if command_type == "voice.speak":
        encoded = parameter.get("gb2312_base64")
        if not isinstance(encoded, str) or not 4 <= len(encoded) <= 320:
            raise CommandRejected("invalid_parameter", "gb2312_base64 must contain 4 to 320 characters")
