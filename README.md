# IoTCmpt AIoT Workspace

ESP32-S3 competition workspace for a sensor + cloud LLM + device-control
system. The project is moving to a protocol-first AIoT architecture:

```text
ESP32-S3 firmware -> MQTT/HTTP -> FastAPI AIoT Gateway -> PostgreSQL/WebSocket -> Next.js console
```

The legacy firmware and backend remain in place until the new path has passed
hardware and demo verification.

## New Architecture

- `firmware/esp32s3/`: new ESP-IDF firmware mainline. It will migrate the
  verified modules from `s3-sensor-cloud/` and replace sensor HTTP polling with
  MQTT telemetry and command topics.
- `server/`: FastAPI AIoT Gateway. It owns MQTT ingestion, HTTP APIs,
  WebSocket fanout, PostgreSQL persistence, image storage, LLM calls, and
  command validation.
- `web/`: Next.js real-time device console.
- `infra/`: deployment and service configuration for PostgreSQL, EMQX, and
  local demo infrastructure.
- `docs/`: architecture, protocol, data model, and migration contracts.
- `backend/`: legacy FastAPI backend kept for compatibility during migration.
- `s3-sensor-cloud/`: legacy ESP-IDF firmware kept as the verified hardware
  reference until `firmware/esp32s3/` is fully validated.
- `scripts/`: workspace-level setup and firmware build helpers.
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

Start the new AIoT stack:

```powershell
docker compose up --build
```

Run the new server directly:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the new web console directly:

```powershell
cd web
npm install
npm run dev
```

Build the current verified firmware path:

```powershell
& 'C:\Users\lshap\Documents\Code\IoTCmpt\scripts\build.ps1'
```

The build script still targets `s3-sensor-cloud/` while the new firmware
mainline is being assembled.

## Migration Rules

- Treat `docs/` as the contract for new work.
- Do not add new features to legacy `backend/` or `s3-sensor-cloud/` unless
  they are needed to keep the hardware fallback working.
- Keep LLM API keys, Wi-Fi secrets, MQTT credentials, and database passwords out
  of source files.
- MQTT is the sensor/control backbone. HTTP is for images, health checks, and
  dashboard APIs.
- The ESP32-S3 firmware must not call external LLM providers directly in the
  production path; the server owns LLM calls and command validation.
- Do not commit build outputs, local `sdkconfig`, `managed_components/`,
  `dependencies.lock`, uploaded images, database files, or local SDK checkouts.
