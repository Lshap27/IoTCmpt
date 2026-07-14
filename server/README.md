# IoTCmpt Server

`server/` contains two independently started processes:

- **Gateway**: FastAPI, HTTP/WebSocket, MQTT ingestion, MCP Server, MQTT outbox publishing, and realtime relay.
- **AI Worker**: model calls, MCP Host, reports, event decisions, patrol scheduling, and durable job recovery.

They share PostgreSQL/TimescaleDB. Only the Worker loads provider credentials and model settings, so an LLM outage does not stop telemetry, manual commands, or firmware-local safety.

## Boundaries

- `app/domain/`: framework-free device, command, AI-run, and policy rules.
- `app/application/`: query, command, report, and diagnostic use cases.
- `app/ports/`: database, MQTT, LLM, MCP, clock, and ID interfaces.
- `app/adapters/`: SQLAlchemy, MQTT, MCP, model, outbox, and realtime implementations.
- `app/api/`: FastAPI transport adapter.
- `app/main.py`: Gateway composition.
- `app/worker_main.py`: Worker composition.

HTTP, MQTT, and MCP enter the same application services. Adapters must not bypass command validation to publish MQTT directly. `tests/test_architecture.py` enforces the import direction.

## Reliable jobs

AI Runs, MQTT Outbox messages, and Realtime Events use PostgreSQL row leases. Each claim gets a unique `lease_token`; renew, complete, fail, and retry operations match `id + lease_owner + lease_token`. A stale worker therefore cannot commit side effects after losing ownership.

AI control idempotency is derived from `run_id + round + call_index`, so a Worker retry cannot create a second hardware command. Cancellation and lease ownership are rechecked before model calls, MCP calls, and final completion.

## Local run

Start root Docker `postgres` and `emqx`, then use two PowerShell 7 windows:

```powershell
cd server
uv sync
Copy-Item .env.example .env
uv run alembic upgrade head
uv run python run_dev.py
```

```powershell
cd server
uv run python run_worker.py
```

The Gateway remains single-process; Workers may scale. Docker Compose starts both services. Generate the shared, browser-inaccessible `AIOT_MCP_INTERNAL_TOKEN` with the setup panel.

## Interfaces and diagnostics

- Application HTTP is versioned under `/api/v1`.
- MCP is Streamable HTTP at `/mcp`; external access is off by default and read/control tokens must differ.
- WebSocket v2 is `/ws/devices/{device_id}`.
- `/health/ready` reports database, MQTT, Worker, MCP, and migration state. A Worker outage degrades readiness without disabling manual control.
- `/api/v1/diagnostics/overview` exposes non-secret queue, heartbeat, MCP, and capability state.
- `/api/v1/diagnostics/traces/{trace_id}` returns the ordered cross-component timeline.

## Migrations

Only add revisions under `alembic/versions/`; never edit an applied migration. `0006` introduces architecture v2, `0007` performs the reliable-worker cutover and legacy AI migration, and `0008` adds lease fencing and MQTT inbox idempotency.

## Checks and generation

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run python scripts/export_openapi.py
cd ..\web
pnpm codegen
```

Unit tests use SQLite and do not require PostgreSQL or EMQX. Dual-Worker leases and full MQTT loops are Docker integration tests. Never commit real `.env` files, provider keys, MCP tokens, or broker credentials.
