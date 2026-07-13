# AGENTS.md

## Command Rules

- Run PowerShell commands with PowerShell 7:
  `C:\Program Files\PowerShell\7\pwsh.exe`.
- This root directory is the workspace Git repository. Check nested reference
  repositories separately before using Git commands inside them.
- The repository may have user edits in progress. Inspect `git status --short`
  before changing files, and do not revert unrelated changes.
- Prefer `rg` / `rg --files` for source discovery when available.

## Current Mainline

- This repository now keeps only the AIoT mainline:
  `docs/`, `server/`, `web/`, `infra/`, `firmware/esp32s3/`, and root
  `docker-compose.yml`.
- Older `backend/`, `s3-sensor-cloud/`, `legacy/`, and compatibility-era HTTP
  sensor upload paths are historical only. Do not route new work there unless an
  older branch or restored checkout actually contains them.
- Treat `docs/architecture.md`, `docs/protocol-mqtt.md`,
  `docs/protocol-http.md`, `docs/protocol-websocket.md`, and
  `docs/data-model.md` as the implementation contract.
- MQTT is the telemetry/control backbone. HTTP is for health checks, dashboard
  APIs, manual actions, AI analysis triggers, and JPEG image upload.
- The end-to-end loop is:
  ESP32-S3 sensing -> MQTT telemetry -> FastAPI gateway -> LLM decision ->
  MQTT command -> device action -> WebSocket dashboard.

## System Responsibilities

- `firmware/esp32s3/` is the ESP-IDF firmware for ESP32-S3-DevKitC-1.
- `server/` is the FastAPI AIoT gateway. It owns MQTT ingestion, HTTP APIs,
  TimescaleDB/PostgreSQL writes, image storage, LLM provider calls, JSON
  command validation, MQTT command publishing, and WebSocket fanout.
- `web/` is a Next.js real-time control console, not a marketing landing page.
  The first screen should remain the working dashboard.
- `infra/` documents local deployment targets and service configuration.
- Root `docker-compose.yml` is the default local stack: TimescaleDB
  (PostgreSQL 16), EMQX, FastAPI server, and Next.js web console.

## Protocol Contract

- MQTT topics:
  `devices/{device_id}/status`,
  `devices/{device_id}/telemetry`,
  `devices/{device_id}/event`,
  `devices/{device_id}/command`,
  `devices/{device_id}/command_ack`, and
  `devices/{device_id}/log`.
- Default demo device id is `esp32s3-001`.
- Server HTTP/WebSocket entry points include:
  `GET /health`, `GET /api/devices`,
  `GET /api/devices/{device_id}/latest`,
  `GET /api/devices/{device_id}/history`,
  `GET /api/devices/{device_id}/history/bucketed`,
  `POST /api/devices/{device_id}/images`,
  `POST /api/devices/{device_id}/commands`,
  `GET/POST /api/devices/{device_id}/notifications`,
  `POST /api/devices/{device_id}/ai/analyze`,
  `GET/PUT /api/devices/{device_id}/autopilot`, and
  `WS /ws/devices/{device_id}`.
- Firmware must publish command acknowledgements with `executed`, `rejected`,
  or `failed`. Unsupported commands should be rejected, not silently executed.
- The frontend reads initial state through HTTP and then applies WebSocket
  envelopes. It must not connect directly to PostgreSQL or MQTT.

## LLM and Autopilot

- Keep all LLM provider integration in `server/`; firmware and frontend must
  not call external LLM providers directly.
- LLM integration is OpenAI-compatible `chat/completions`. Ordinary analysis is
  text-only; only explicit and scheduled vision analysis may attach a fresh JPEG.
- `AIOT_LLM_ENDPOINT=mock` is the deterministic offline/demo mode and should
  keep the full AI decision loop testable without network access or API keys.
- AI-generated commands are persisted before publishing. Only executable
  high-confidence commands are sent to MQTT; low-confidence decisions remain
  pending suggestions.
- Autopilot state is per-device and in-memory. It resets from
  `AIOT_AUTOPILOT_ENABLED` on server restart.

## Firmware Build and Boundaries

- Firmware mainline is `firmware/esp32s3/`.
- From the repository root, use PowerShell 7 and build with:

  ```powershell
  cd firmware\esp32s3
  idf.py -B build-esp32s3 build
  ```

- The current checkout does not contain `scripts/build.ps1`; do not cite it as
  the active build entrypoint unless that script is restored and verified.
- Primary framework is ESP-IDF v5.5.2. Prefer the EIM/VS Code ESP-IDF setup if
  present; otherwise use the active shell's ESP-IDF environment.
- Default firmware configuration disables Wi-Fi, MQTT, image upload, camera,
  display, actuators, and button modules so the project can compile without
  local credentials or attached hardware.
- Enable runtime features through `idf.py menuconfig` or a local `sdkconfig`.
  Do not commit local `sdkconfig` or secrets.
- Keep `app_main` as an orchestrator: load config, initialize modules, and start
  tasks. Do not collapse hardware logic into one monolithic function.
- Keep local runtime state in `main/state/`; do not store manual
  override/window/alarm state inside sensor samples.
- `main/Kconfig` user-facing titles are intentionally Chinese. Do not rename
  `APP_*` config symbols without updating all dependent C code.
- OV2640 camera configuration currently uses PWDN, SIOD/SIOC, D0-D7, VSYNC,
  HREF, and PCLK. Do not invent unsupported camera pins or Kconfig symbols
  without matching hardware and source changes.

## Server Workflow

- Dependencies are managed with uv (`server/pyproject.toml` + `server/uv.lock`).
  Direct local run (requires the Docker `postgres` + `emqx` services):

  ```powershell
  cd server
  uv sync
  Copy-Item .env.example .env   # enables AIOT_MQTT_ENABLED=true
  uv run alembic upgrade head
  uv run python run_dev.py
  ```

- `run_dev.py` starts uvicorn with the Windows `SelectorEventLoop` policy that
  aiomqtt requires. Without a `.env`, `AIOT_MQTT_ENABLED` defaults to `false`
  and the gateway starts silently without MQTT ingestion.
- Server checks:

  ```powershell
  cd server
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy app
  uv run pytest
  ```

- Tests must run without PostgreSQL or EMQX. They use SQLite and environment
  overrides from `server/tests/conftest.py`.
- Schema changes go through Alembic (`server/alembic/versions/`); keep
  `AIOT_AUTO_CREATE_TABLES=false` wherever migrations own the schema. The
  `telemetry` table is a TimescaleDB hypertable (migration `0002`).
- After changing schemas or routes, regenerate the API contract:
  `uv run python scripts/export_openapi.py`, then `pnpm codegen` in `web/`.
  CI fails on drift between code, `server/openapi.json`, and
  `web/src/lib/api-client/`.
- Configuration uses `AIOT_*` environment variables and `server/.env` for local
  direct runs. Keep real `.env` files untracked.

## Web Workflow

- Direct local run:

  ```powershell
  cd web
  pnpm install
  pnpm dev
  ```

- Verification:

  ```powershell
  cd web
  pnpm lint
  pnpm format:check
  pnpm typecheck
  pnpm build
  ```

- The app uses Next.js 15, React 19, TypeScript, Tailwind CSS v4 (CSS-first
  `@theme` in `src/app/globals.css`), shadcn/ui (`src/components/ui/`),
  TanStack Query, Recharts, and lucide-react. Keep UI work dashboard-first and
  consistent with the existing component structure under
  `web/src/components/`.
- Data flow: initial reads go through TanStack Query; WebSocket envelopes are
  applied to the query cache by `src/lib/ws-dispatcher.ts`. Do not reintroduce
  ad-hoc `useEffect` fetching.
- `src/lib/api-client/` is generated from `server/openapi.json` by
  `@hey-api/openapi-ts`. Never edit it by hand; run `pnpm codegen`.
- Use `NEXT_PUBLIC_API_BASE_URL` when the FastAPI server is not on
  `http://localhost:8000`.

## Quality Gates

- `pre-commit run --all-files` must pass (end-of-file/whitespace/YAML checks,
  Ruff lint + format, Prettier, clang-format).
- GitHub Actions: `.github/workflows/server.yml` (Ruff, mypy, pytest, and an
  OpenAPI codegen-drift job), `web.yml` (lint, format, typecheck, build), and
  `firmware.yml` (ESP-IDF build).

## Local Stack

- Start the full local demo stack from the repository root:

  ```powershell
  docker compose up --build
  ```

- Default local services:
  TimescaleDB/PostgreSQL `localhost:5432`, EMQX MQTT `localhost:1883`, EMQX
  dashboard `http://localhost:18083`, FastAPI `http://localhost:8000`, Next.js
  `http://localhost:3000`.
- Default EMQX dashboard credentials are `admin / public`; anonymous MQTT is
  only acceptable for the first local demo stack.
- For real device demos on the same Wi-Fi, configure firmware targets with the
  laptop IP: MQTT `<laptop-ip>:1883` and image/API base
  `http://<laptop-ip>:8000`.

## Secrets and Generated Files

- Do not put LLM API keys, Wi-Fi credentials, MQTT credentials, cloud tokens, or
  non-demo database passwords in firmware, frontend, docs, or committed config.
- Do not commit build outputs, `managed_components/`, `sdkconfig*`, binaries,
  uploaded images, captured images, virtual environments, frontend build
  output, database files, or local SDK/reference checkouts.
- Committed generated artifacts are intentional exceptions: keep
  `server/openapi.json`, `web/src/lib/api-client/`, and
  `firmware/esp32s3/dependencies.lock` (pins ESP-IDF component versions)
  tracked, and refresh them through their generators rather than editing by
  hand.
- `references/` is ignored and may contain large local SDK/reference clones.
  Treat it as local support material unless the user explicitly asks otherwise.
- Keep `.agents/`, `.codex/`, `.claude/`, local `.env` files, logs, and editor
  transients out of committed project state.
