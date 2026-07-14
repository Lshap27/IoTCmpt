# AGENTS.md

## Workspace rules

- Use PowerShell 7 (`C:\Program Files\PowerShell\7\pwsh.exe`) for Windows commands.
- This directory is the Git root. Inspect `git status --short` before edits and preserve unrelated work.
- Prefer `rg` and `rg --files` for discovery.
- The active mainline is `contracts/`, `docs/`, `firmware/esp32s3/`, `server/`, `web/`, `infra/`, root `docker-compose.yml`, and the local tools under `tools/`.
- Treat `docs/architecture.md`, protocol documents, `contracts/*.json`, and `server/openapi.json` as implementation contracts.

## Current architecture

IoTCmpt is a modular monolith at the Gateway boundary with a separate durable AI Worker process:

```text
ESP32-S3 / firmware simulator <-- MQTT v2 --> Gateway <-- HTTP v1 / WS v2 --> Web
                                              ^
                                              +-- MCP /mcp <-- AI Worker --> LLM
                                                        |
                                      PostgreSQL / TimescaleDB
```

- Firmware owns sensing, actuators, local smoke safety, priority and command idempotency.
- Gateway owns HTTP, WebSocket, MQTT ingestion, MCP Server, device state, command lifecycle, outbox and trace relay.
- Worker owns model calls, reports, event analysis and patrol scheduling. It reaches device operations only through MCP.
- Web owns presentation, manual actions and per-device policy configuration. It never connects to MQTT, PostgreSQL or an LLM.
- PostgreSQL is the durable coordination layer. AI Run, MQTT outbox and realtime relay claims use owner plus unique `lease_token` fencing.

## Protocol contract

MQTT v2 topics:

- `devices/{device_id}/status`
- `devices/{device_id}/capabilities`
- `devices/{device_id}/telemetry`
- `devices/{device_id}/event`
- `devices/{device_id}/command`
- `devices/{device_id}/command_ack`
- `devices/{device_id}/log`

Every message uses the v2 envelope from `contracts/mqtt-envelope.schema.json`. Firmware accepts only v2 commands. Commands are validated against `contracts/commands.json`, acknowledged first as `accepted`, then as `executed`, `rejected`, or `failed`. Repeated `command_id` values replay the stored terminal ACK without repeating hardware work.

Application APIs are versioned under `/api/v1`; there is no active unversioned compatibility API. Important entry points:

- `GET /health`, `GET /health/ready`
- `GET /api/v1/devices`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history`
- `GET /api/v1/devices/{device_id}/capabilities`
- `POST /api/v1/devices/{device_id}/commands`
- `POST /api/v1/devices/{device_id}/images`
- `POST /api/v1/devices/{device_id}/ai/runs`
- `GET/PUT /api/v1/devices/{device_id}/automation-policy`
- `GET /api/v1/diagnostics/overview`
- `GET /api/v1/diagnostics/traces/{trace_id}`
- `POST /mcp` (Streamable HTTP with scoped bearer tokens)
- `WS /ws/devices/{device_id}`

AI Run creation always returns `202` and continues asynchronously. Active states include `queued`, `running`, `waiting_model`, `calling_tool`, and `waiting_device`; terminal states are `succeeded`, `failed`, `cancelled`, and `skipped`.

## Server workflow

Dependencies are managed with uv (`server/pyproject.toml` and `server/uv.lock`). Direct development requires PostgreSQL and EMQX:

```powershell
cd server
uv sync
Copy-Item .env.example .env
uv run alembic upgrade head
uv run python run_dev.py
# second PowerShell window
uv run python run_worker.py
```

The Gateway must stay single-process. Worker processes may scale horizontally. Provider keys and model settings belong only to the Worker. `AIOT_LLM_ENDPOINT=mock` must exercise the same persistent AI -> MCP -> command path as an online provider.

Server checks:

```powershell
cd server
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

Tests default to SQLite and must not require PostgreSQL or EMQX. Concurrency, migrations and end-to-end behavior additionally require the Docker stack. Schema changes use new Alembic revisions; do not edit an applied revision.

After route or schema changes:

```powershell
cd server
uv run python scripts/export_openapi.py
cd ..\web
pnpm codegen
```

Never hand-edit `web/src/lib/api-client/`.

## Firmware workflow and board boundary

Firmware mainline is `firmware/esp32s3/`, targeting ESP-IDF 5.5.2. Build after loading the ESP-IDF environment:

```powershell
cd firmware\esp32s3
idf.py -B build build
```

- `app_main` composes modules; drivers, state, local rules, protocol and command registry remain separate.
- Default configuration is safe and compile-oriented: physical modules, networking, image upload and simulated sensor data are disabled.
- `configs/full-hardware.defaults` is a compile-check profile, not a flash-ready board profile.
- Real-board configuration must pass duplicate-GPIO, native-USB GPIO19/20 and octal-PSRAM GPIO35-37 checks.
- OV2640 currently uses the verified PWDN-only design with `pin_xclk=-1`; do not invent a clock pin without board evidence.
- Local `sdkconfig` contains machine-specific addresses and may contain credentials. Never commit it.

Compilation and simulation do not prove USB enumeration, power integrity, actual GPIO wiring, PSRAM, camera timing, display, voice, sensor levels or mechanical actuator movement. State those limitations plainly whenever no physical board was tested.

## Firmware simulator and setup panel

`tools/simulate-device.py` starts the lightweight firmware behavior simulator. Its implementation lives in `tools/firmware_simulator/` and shares generated behavior/command contracts with firmware.

```powershell
server\.venv\Scripts\python.exe tools\simulate-device.py --scenario normal
```

Scenarios are `normal`, `air-watch`, `air-alert`, and `smoke`. It uses real MQTT/HTTP, a 100 ms local safety loop, command queueing, ACK replay and simulated NVS under `.runtime/firmware-simulator/`. It is for integration and demos, not electrical validation.

The setup panel is started by `启动配置面板.cmd`, listens only on `127.0.0.1:8765`, and protects writes with a per-process Panel Token. `config/runtime-config.json` is the configuration catalog and `tools/runtime_config.py` is the only writer for root/server/web environment files. Secrets are displayed only as “已配置”. Per-device automation policies belong in the Web console, not startup configuration.

## Web workflow

```powershell
cd web
pnpm install
pnpm dev

pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
pnpm test:e2e
```

The app uses Next.js 15, React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query and Recharts. `/` is the operational dashboard, `/admin` is the counselor product view, and `/diagnostics` is the non-secret engineering view.

Initial state is loaded through HTTP. WebSocket v2 events update Query Cache through `web/src/lib/ws-dispatcher.ts`; `event_id` deduplication and irreversible terminal command status must be preserved. Reconnect invalidates snapshots, commands, capabilities, AI Runs and policy queries.

## Quality gates and cleanup

```powershell
python tools/generate-contracts.py --check
pre-commit run --all-files
docker compose up --build
```

Do not commit `.env`, `web/.env.local`, firmware `sdkconfig`, credentials, `.runtime/`, build directories, `managed_components/`, `.next/`, `*.tsbuildinfo`, caches, uploads, local SDKs or test output. Intentionally tracked generated artifacts are `server/openapi.json`, `web/src/lib/api-client/`, firmware generated headers and `firmware/esp32s3/dependencies.lock`.
