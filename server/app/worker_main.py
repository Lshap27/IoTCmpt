from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from uuid import uuid4

from app.adapters.ai_worker import AiRunWorker, PatrolScheduler
from app.adapters.job_store import SqlAlchemyJobStore
from app.adapters.mcp_client import McpToolClient
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.llm import LLMService

LOGGER = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    if settings.auto_create_tables:
        init_db()
    if not settings.mcp_internal_token:
        raise RuntimeError("AIOT_MCP_INTERNAL_TOKEN is required by the AI worker")

    instance_id = f"worker-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
    store = SqlAlchemyJobStore(
        SessionLocal,
        instance_id,
        lease_seconds=settings.ai_worker_lease_seconds,
        max_attempts=settings.ai_worker_max_attempts,
    )
    mcp = McpToolClient(
        settings.gateway_internal_url,
        settings.mcp_internal_token,
        settings.llm_timeout_seconds,
    )
    worker = AiRunWorker(settings, SessionLocal, LLMService(settings), mcp, store)
    scheduler = PatrolScheduler(settings, SessionLocal, store)
    worker.start()
    scheduler.start()
    LOGGER.info("AI worker started instance_id=%s", instance_id)
    try:
        await asyncio.Event().wait()
    finally:
        await scheduler.stop()
        await worker.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
