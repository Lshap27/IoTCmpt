from __future__ import annotations

import base64

from app.application.commands import CommandApplicationService
from app.domain.commands import CommandRejected, CommandRequest, CommandSource

VOICE_TEXT_MAX_BYTES = 220


def encode_voice_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise CommandRejected("invalid_parameter", "speech text must not be blank")
    encoded = normalized.encode("gb2312", errors="replace")
    if len(encoded) > VOICE_TEXT_MAX_BYTES:
        raise CommandRejected(
            "invalid_parameter",
            f"speech text exceeds the SYN6288 {VOICE_TEXT_MAX_BYTES}-byte GB2312 limit",
        )
    return base64.b64encode(encoded).decode("ascii")


async def submit_speech(
    commands: CommandApplicationService,
    *,
    device_id: str,
    text: str,
    source: CommandSource,
    reason: str,
    trace_id: str,
    idempotency_key: str | None,
    ai_restricted: bool = False,
) -> dict:
    return await commands.submit(
        CommandRequest(
            device_id=device_id,
            type="voice.speak",
            parameter={"gb2312_base64": encode_voice_text(text)},
            source=source,
            reason=reason,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        ),
        ai_restricted=ai_restricted,
    )
