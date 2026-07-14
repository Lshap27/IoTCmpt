"""Windows-friendly entry point for the independent AI worker process."""

from __future__ import annotations

import asyncio
import sys

from app.worker_main import main

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
