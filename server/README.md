# AIoT Gateway Server

FastAPI gateway for the AIoT architecture.

Responsibilities:

- Subscribe to device MQTT topics (aiomqtt, single asyncio event loop with
  automatic reconnect).
- Store device status, telemetry, events, commands, AI results, and image
  assets in TimescaleDB/PostgreSQL (telemetry is a hypertable).
- Publish validated commands to MQTT.
- Expose HTTP APIs for the web console; every endpoint declares a
  `response_model`, and `openapi.json` is the committed API contract.
- Broadcast live updates through WebSocket (`WsMessage` discriminated union).
- Keep LLM provider credentials on the server side only.

Tooling: dependencies are managed with uv (`pyproject.toml` + `uv.lock`),
linting/formatting with Ruff, type checking with mypy, migrations with
Alembic.

## Local Run

Requires the Docker `postgres` and `emqx` services from the repo root.

```powershell
cd server
uv sync
Copy-Item .env.example .env   # enables AIOT_MQTT_ENABLED=true for direct runs
uv run alembic upgrade head
uv run python run_dev.py
```

`run_dev.py` starts uvicorn with the Windows `SelectorEventLoop` policy that
aiomqtt requires. Without a `.env`, `AIOT_MQTT_ENABLED` defaults to `false`
and the gateway starts without MQTT ingestion (no error is raised).

## Test and Checks

```powershell
cd server
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

The test suite must run without PostgreSQL or EMQX. It uses SQLite and
disables MQTT through environment overrides in `tests/conftest.py`.

## API Contract

After changing schemas or routes, re-export the OpenAPI document and
regenerate the frontend client:

```powershell
uv run python scripts/export_openapi.py
cd ..\web
pnpm codegen
```

CI (`.github/workflows/server.yml`) fails when `openapi.json` or the
generated client drifts from the code.

## Migrations

Schema changes go through Alembic (`alembic/versions/`). `0001` creates the
initial schema; `0002` converts `telemetry` into a TimescaleDB hypertable.
Apply with `uv run alembic upgrade head`. The Docker image runs
`alembic upgrade head` on start; `AIOT_AUTO_CREATE_TABLES` stays `false`
whenever migrations manage the schema.

## Environment

Copy `.env.example` to `.env` for local direct-run configuration. Keep real
LLM keys and MQTT credentials out of source control.
