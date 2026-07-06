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
- FastAPI AIoT Gateway: subscribes to MQTT, exposes HTTP APIs, stores data in
  PostgreSQL, saves images, calls the LLM provider, validates generated commands,
  publishes commands to MQTT, and fans out updates over WebSocket.
- PostgreSQL: stores devices, telemetry, events, commands, AI decisions, and
  image metadata.
- Next.js console: reads initial state through HTTP and receives live updates
  through WebSocket.

## Data Flow

1. Firmware boots and publishes `devices/{device_id}/status` with `online`.
2. Firmware publishes periodic telemetry to `devices/{device_id}/telemetry`.
3. Server stores telemetry and broadcasts a WebSocket `telemetry` event.
4. Firmware uploads images to `POST /api/devices/{device_id}/images`.
5. Frontend or server asks for AI analysis through
   `POST /api/devices/{device_id}/ai/analyze`.
6. Server calls the LLM provider, validates the result, stores an `ai_result`,
   creates a command, and publishes it to `devices/{device_id}/command`.
7. Firmware executes the command and publishes `command_ack`.
8. Server stores the acknowledgement and broadcasts a WebSocket `command_ack`
   event.

## Deployment Topology

Local demo deployment uses root `docker-compose.yml`:

- `postgres`: PostgreSQL database.
- `emqx`: MQTT broker and dashboard.
- `server`: FastAPI gateway on port 8000.
- `web`: Next.js console on port 3000.

The ESP32-S3 connects to the host IP on MQTT port 1883 and HTTP port 8000.

## Migration Stance

The old `backend/` and `s3-sensor-cloud/` directories are compatibility
references. New features target `server/`, `web/`, `infra/`, and
`firmware/esp32s3/`. Existing verified hardware code should be migrated rather
than reimplemented from scratch.

