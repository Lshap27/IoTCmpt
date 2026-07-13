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

### Visual setup panel (recommended)

On Windows, double-click `启动配置面板.cmd`. The local-only panel at
`127.0.0.1:8765` provides environment checks, project configuration, service
control, firmware configuration, firmware operations, and local data tools.

1. Run the Environment Center check. It can install missing prerequisites,
   test Docker Hub access, select the official registry/a public mirror, and
   configure Docker Desktop to use a detected local proxy.
2. ESP-IDF detection and repair are centralized in the Environment Center. It
   validates the framework, Python environment, CMake, Ninja, ESP32-S3 Xtensa
   toolchain, and OpenOCD. It reads the current setup from ESP-IDF Installation
   Manager (EIM), including custom `idf.eimIdfJsonPath` locations, and keeps a
   legacy-install fallback. Working ESP-IDF releases `>=5.1,<6.0` are accepted.
3. Select the device source and AI mode independently, then save.
4. Start the Docker demo stack. In Virtual Device mode, the panel waits for
   MQTT and the API, then starts the host simulator automatically.
5. Open `http://localhost:3000`. Health is at `http://localhost:8000/health`;
   EMQX is at `http://localhost:18083` (`admin / public`).

The Data Tools page can preview or selectively clean a device's records in a
local time range, and can replace telemetry/events in that range with a
deterministic five-stage demo. It runs only through the loopback-only setup
panel and does not expose a public FastAPI administration route.

The four supported combinations are Virtual Device + Mock AI (recommended
offline demo), Virtual Device + Online LLM, Real ESP32-S3 + Mock AI, and Real
ESP32-S3 + Online LLM. The default air-alert simulator publishes real MQTT
telemetry/events; the backend persists them, runs Mock AI, publishes autopilot
commands, and receives command acknowledgements from the simulator. It is not
frontend-only sample data.

Risky settings are constrained: autopilot levels are selected from `good`,
`watch`, and `alert`, confidence is limited to `0..1`, and device IDs, URLs,
intervals, and dependent firmware fields are validated in both the browser and
backend/tooling.

The generated `.env`, `server/.env`, `web/.env.local`, and firmware `sdkconfig`
are local files ignored by Git. Never commit Wi-Fi passwords or LLM API keys.

### Real device and firmware

Real Device mode generates LAN-reachable MQTT and image-upload addresses.
Firmware Operations now only handles menuconfig, build, flash, and monitor;
repair the ESP-IDF environment from the Environment Center.

Firmware “mock sensor data” still runs on a physical ESP32-S3 and replaces only
sensor readings. “Virtual Device” is a complete host-side MQTT device simulator
and requires no board.

### Command-line development

Use PowerShell 7 for manual Windows commands. Start the full AIoT stack
(TimescaleDB, EMQX, server, web):

```powershell
docker compose up --build
```

Run the virtual device manually after MQTT and the API are ready:

```powershell
server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-alert --device-id esp32s3-001
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

Build the firmware after loading an ESP-IDF environment:

```powershell
cd firmware\esp32s3
idf.py -B build build
```

VS Code tasks remain available as shortcuts in `.vscode/tasks.json`; the visual
panel's Environment Center is the single entry point for ESP-IDF diagnosis and
repair.

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
