# AIoT Architecture

## System Goal

The system is a complete competition-grade AIoT loop:

```text
ESP32-S3 sensing -> MQTT telemetry -> FastAPI AIoT Gateway -> LLM decision -> MQTT command -> device action -> WebSocket dashboard
```

The firmware collects fused sensor data and images. The server validates,
persists, enriches, and distributes state. The frontend is a real-time control
console for demonstration and debugging.

## Components

- ESP32-S3 firmware: reads SHT30, TVOC301, LM393, OV2640, button, display, SG90,
  and beeper modules. It publishes status/telemetry/event/log messages to MQTT,
  uploads JPEG images over HTTP, subscribes to command messages, and publishes
  command acknowledgements.
- EMQX: MQTT broker for device-to-server and server-to-device messages. It is
  also useful during demos because its dashboard exposes topic activity.
- FastAPI AIoT Gateway: subscribes to MQTT with an asyncio-native client
  (aiomqtt, automatic reconnect), exposes HTTP APIs, stores data in
  TimescaleDB, saves images, calls the LLM provider, validates generated
  commands, publishes commands to MQTT, and fans out updates over WebSocket.
  Gateway singletons (MQTT client, autopilot) live on `app.state` and are
  injected into routes with FastAPI dependencies.
- TimescaleDB (PostgreSQL 16 + timescaledb): stores devices, telemetry,
  events, commands, AI decisions, and image metadata. The `telemetry` table is
  a hypertable partitioned on `sampled_at`; the schema is managed by Alembic
  migrations.
- Next.js console: reads initial state through HTTP (TanStack Query) and
  receives live updates through WebSocket. A pure dispatcher maps each
  WebSocket envelope onto the query cache.

## Contract Single Source

The HTTP/WebSocket wire contract is exported from the FastAPI app into
`server/openapi.json` (`server/scripts/export_openapi.py`), which also embeds
the `WsMessage` discriminated union used by the WebSocket stream. The
frontend client under `web/src/lib/api-client/` is generated from that file
with `@hey-api/openapi-ts` (`pnpm codegen`). Both artifacts are committed,
and CI fails when either drifts from the code.

## Data Flow

1. Firmware boots and publishes `devices/{device_id}/status` with `online`.
2. Firmware publishes periodic telemetry to `devices/{device_id}/telemetry`.
3. Server stores telemetry and broadcasts a WebSocket `telemetry` event.
4. Firmware uploads images to `POST /api/devices/{device_id}/images`.
5. An AI analysis starts in one of two ways:
   - automatically ("autopilot"): incoming telemetry matches the trigger rules
     (`fusion.air_quality` in the configured levels, or `fusion.alarm_enabled`),
     the per-device switch is on, and the cooldown has expired; or
   - manually: the frontend calls `POST /api/devices/{device_id}/ai/analyze`.
6. Server broadcasts `ai_analyzing`, then calls the LLM provider with the
   device snapshot, a recent telemetry trend, and — when fresh — the latest
   JPEG as an OpenAI-compatible vision message. The validated decision is
   stored as an `ai_result` plus a command.
7. If the command type is executable and its confidence passes the configured
   gate, the server publishes it to `devices/{device_id}/command`; otherwise it
   is kept as a pending suggestion. Either way an `ai_result` WebSocket event
   is broadcast.
8. Firmware executes the command and publishes `command_ack`.
9. Server stores the acknowledgement and broadcasts a WebSocket `command_ack`
   event.
10. On demand, the dashboard calls `POST /api/devices/{device_id}/ai/report`
    for an hour, day, or week. The server aggregates stored telemetry and
    events, calculates data completeness, and asks the LLM for an auditable
    health report with anomalies and prioritized actions.

The LLM integration is OpenAI-compatible (any provider exposing
`chat/completions`), supports optional strict `json_schema` response formats,
and offers a deterministic `mock` mode so the full closed loop can be
demonstrated without network access or API keys.

DeepSeek V4 uses the same transport. When thinking mode is enabled the gateway
sends `thinking.type` and `reasoning_effort` and omits temperature. DeepSeek's
current chat models are text-only, so deployments using them should set
`AIOT_LLM_VISION_ENABLED=false`.

## Deployment Topology

Local demo deployment uses root `docker-compose.yml`:

- `postgres`: TimescaleDB (PostgreSQL 16). The server container applies
  Alembic migrations on start.
- `emqx`: MQTT broker and dashboard.
- `server`: FastAPI gateway on port 8000.
- `web`: Next.js console on port 3000.

The ESP32-S3 connects to the host IP on MQTT port 1883 and HTTP port 8000.

## Mainline Stance

The repository keeps the current AIoT mainline only. New features target
`server/`, `web/`, `infra/`, and `firmware/esp32s3/`. MQTT remains the device
telemetry/control contract, and HTTP remains limited to images, health checks,
and dashboard APIs.
