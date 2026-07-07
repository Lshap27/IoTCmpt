"""Windows-friendly dev entry point.

aiomqtt requires a selector event loop; the default Windows Proactor loop does not
support loop.add_reader. Run `python run_dev.py` locally on Windows (or use
docker compose, where the Linux loop works out of the box).

Note: reload is disabled here because uvicorn's reloader re-creates the event
loop in a subprocess where the selector policy would not apply. For hot-reload
on bare Windows, run `uvicorn app.main:app --reload` with AIOT_MQTT_ENABLED=false.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8000)
    asyncio.run(uvicorn.Server(config).serve())
