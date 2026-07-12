# IoTCmpt AIoT Workspace

ESP32-S3 competition workspace for a protocol-first AIoT system:

```text
ESP32-S3 firmware -> MQTT/HTTP -> FastAPI AIoT Gateway -> TimescaleDB/WebSocket -> Next.js console
```

The repository keeps only the AIoT mainline. MQTT is the telemetry and control
backbone. HTTP is used for health checks, dashboard APIs, and JPEG image
upload. The HTTP/WebSocket contract has a single source of truth:
`server/openapi.json`, from which the frontend API client is generated.

## Architecture

- `firmware/esp32s3/`: ESP-IDF (v5.5.2) firmware for ESP32-S3-DevKitC-1.
- `server/`: FastAPI AIoT Gateway — async MQTT ingestion (aiomqtt), HTTP APIs,
  WebSocket fanout, TimescaleDB persistence (Alembic migrations), image
  storage, LLM calls, and command validation. Managed with uv; linted with
  Ruff; type-checked with mypy.
- `web/`: Next.js 15 + React 19 real-time device console — Tailwind CSS v4,
  shadcn/ui, TanStack Query, and a generated OpenAPI client
  (`@hey-api/openapi-ts`).
- `infra/`: deployment notes and service configuration.
- `docs/`: architecture, protocol, and data model contracts.

## Protocol Entry Points

MQTT topics:

- `devices/{device_id}/status`
- `devices/{device_id}/telemetry`
- `devices/{device_id}/event`
- `devices/{device_id}/command`
- `devices/{device_id}/command_ack`
- `devices/{device_id}/log`

HTTP and WebSocket APIs:

- `GET /health`
- `GET /api/devices`
- `GET /api/devices/{device_id}/latest`
- `GET /api/devices/{device_id}/history`
- `GET /api/devices/{device_id}/history/bucketed`
- `POST /api/devices/{device_id}/images`
- `POST /api/devices/{device_id}/ai/analyze`
- `POST /api/devices/{device_id}/commands`
- `GET/PUT /api/devices/{device_id}/autopilot`
- `WS /ws/devices/{device_id}`

See `docs/` for the full wire contracts. The machine-readable contract is
`server/openapi.json` (exported by `server/scripts/export_openapi.py`; CI
fails on drift).

## Local Development

Use PowerShell 7 on Windows for manual development commands. VS Code tasks use
the built-in Windows PowerShell (`powershell.exe`), so teammates do not need to
install PowerShell 7 just to configure or start the local demo.

Start the full AIoT stack (TimescaleDB, EMQX, server, web):

```powershell
docker compose up --build
```

Run the server directly (requires Docker `postgres` + `emqx` running):

```powershell
cd server
uv sync
Copy-Item .env.example .env   # sets AIOT_MQTT_ENABLED=true for direct runs
uv run alembic upgrade head
uv run python run_dev.py
```

Note: without a `.env`, MQTT ingestion defaults to disabled
(`AIOT_MQTT_ENABLED=false`) and the gateway starts silently without it.

Run the web console directly:

```powershell
cd web
pnpm install
pnpm dev
```

Build the firmware:

For the first firmware task on a machine, or if `idf.py` cannot be found, run
`固件：安装/修复 ESP-IDF 环境` from VS Code Tasks first. It installs or repairs
the ESP-IDF tools and Python environment for ESP32-S3. The firmware Tasks then
load the detected ESP-IDF environment automatically.

```powershell
cd firmware\esp32s3
idf.py -B build build
```

## Quality Checks

```powershell
# server
cd server
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app ; uv run pytest

# web
cd web
pnpm lint ; pnpm format:check ; pnpm typecheck ; pnpm build

# whole repo
pre-commit run --all-files

# regenerate the API contract after changing server schemas/routes
cd server ; uv run python scripts/export_openapi.py
cd ..\web ; pnpm codegen
```

GitHub Actions run the same checks per area (`server.yml` including an
OpenAPI-drift job, `web.yml`, `firmware.yml`).

## Rules

- Treat `docs/` and `server/openapi.json` as the protocol contract. Never edit
  `web/src/lib/api-client/` by hand — regenerate it with `pnpm codegen`.
- Keep LLM API keys, Wi-Fi secrets, MQTT credentials, and database passwords
  out of source files.
- MQTT owns sensor telemetry and commands.
- The ESP32-S3 firmware must not call external LLM providers directly; the
  server owns LLM calls and command validation.
- Do not commit build outputs, local `sdkconfig`, `managed_components/`,
  uploaded images, database files, virtual environments, frontend build
  output, or local SDK checkouts. Committed generated artifacts are the
  exception: `server/openapi.json`, `web/src/lib/api-client/`, and
  `firmware/esp32s3/dependencies.lock` (pins ESP-IDF component versions) are
  tracked on purpose.
