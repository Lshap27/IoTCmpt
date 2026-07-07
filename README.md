# IoTCmpt AIoT Workspace

ESP32-S3 competition workspace for a protocol-first AIoT system:

```text
ESP32-S3 firmware -> MQTT/HTTP -> FastAPI AIoT Gateway -> PostgreSQL/WebSocket -> Next.js console
```

The repository now keeps only the new AIoT mainline. MQTT is the telemetry and
control backbone. HTTP is used for health checks, dashboard APIs, and JPEG image
upload.

## Architecture

- `firmware/esp32s3/`: ESP-IDF firmware for ESP32-S3-DevKitC-1.
- `server/`: FastAPI AIoT Gateway for MQTT ingestion, HTTP APIs, WebSocket
  fanout, PostgreSQL persistence, image storage, LLM calls, and command
  validation.
- `web/`: Next.js real-time device console.
- `infra/`: deployment notes and service configuration.
- `docs/`: architecture, protocol, and data model contracts.
- `scripts/`: workspace setup, firmware build, and simulated-device helpers.
- `references/`: optional local SDKs, docs, and reference repositories.

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
- `POST /api/devices/{device_id}/images`
- `POST /api/devices/{device_id}/ai/analyze`
- `POST /api/devices/{device_id}/commands`
- `WS /ws/devices/{device_id}`

See `docs/` for the full wire contracts.

## Local Development

Use PowerShell 7 on Windows.

Start the AIoT stack:

```powershell
docker compose up --build
```

Run the server directly:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the web console directly:

```powershell
cd web
pnpm install --ignore-scripts
pnpm run dev
```

Build the firmware from the repository root:

```powershell
& 'C:\Users\lshap\Documents\Code\IoTCmpt\scripts\build.ps1'
```

Simulate a device after the server or Compose stack is running:

```powershell
server\.venv\Scripts\python.exe scripts\simulate-device.py --host 127.0.0.1 --device-id esp32s3-001
```

## Rules

- Treat `docs/` as the protocol contract.
- Keep LLM API keys, Wi-Fi secrets, MQTT credentials, and database passwords out
  of source files.
- MQTT owns sensor telemetry and commands.
- The ESP32-S3 firmware must not call external LLM providers directly; the
  server owns LLM calls and command validation.
- Do not commit build outputs, local `sdkconfig`, `managed_components/`,
  `dependencies.lock`, uploaded images, database files, virtual environments,
  frontend build output, or local SDK checkouts.
