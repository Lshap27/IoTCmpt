# Migration Plan

## Phase 1: Protocol and Skeleton

- Add the architecture and protocol documents under `docs/`.
- Add `server/` as the new FastAPI gateway skeleton.
- Add `web/` as the Next.js control console skeleton.
- Add `infra/` and root `docker-compose.yml`.
- Keep `backend/` and `s3-sensor-cloud/` unchanged and buildable.

Acceptance:

- Protocol docs cover telemetry, status, images, AI analysis, commands, ACKs,
  WebSocket events, and persistence.
- New server tests pass without requiring real PostgreSQL or EMQX.
- Docker Compose describes PostgreSQL, EMQX, server, and web.

## Phase 2: Server as Gateway

- Implement PostgreSQL persistence for the new data model.
- Subscribe to MQTT telemetry/status/event/log/command_ack topics.
- Broadcast stored changes through WebSocket.
- Save uploaded images under `uploads/`.
- Migrate LLM command validation from legacy backend.

Acceptance:

- Simulated MQTT telemetry appears in `GET /latest`, `GET /history`, and the
  WebSocket stream.
- Invalid LLM output becomes a `none` command.
- Manual commands are stored and published to MQTT.

## Phase 3: Firmware Adapter

- Create `firmware/esp32s3/` from the current verified ESP-IDF project shape.
- Reuse hardware modules from `s3-sensor-cloud/main/`.
- Add an MQTT client module that publishes status/telemetry and subscribes to
  commands.
- Keep HTTP only for JPEG upload and diagnostics.
- Publish command acknowledgements after actuator execution.

Acceptance:

- Default firmware builds.
- Hardware telemetry reaches the server through MQTT.
- `window.open`, `window.close`, `alarm.on`, and `alarm.off` round-trip through
  command ACKs.

## Phase 4: Demo Console

- Build the first-screen dashboard in `web/`.
- Use HTTP for initial state and WebSocket for live updates.
- Show latest image, AI result, command state, event log, telemetry chart, and
  online state.

Acceptance:

- With a simulated or physical ESP32-S3, the dashboard updates without refresh.
- When the device goes offline, the dashboard shows degraded state.
- EMQX dashboard remains available for low-level MQTT inspection.

## Legacy Mapping

- `backend/app/services/llm_service.py` -> `server/app/services/llm.py`
- `backend/app/services/image_storage.py` -> `server/app/services/images.py`
- `backend/app/services/command_service.py` -> `server/app/services/commands.py`
- `s3-sensor-cloud/main/sensors` -> `firmware/esp32s3/main/sensors`
- `s3-sensor-cloud/main/camera` -> `firmware/esp32s3/main/camera`
- `s3-sensor-cloud/main/actuators` -> `firmware/esp32s3/main/actuators`
- `s3-sensor-cloud/main/backend` -> replaced by MQTT module plus image upload
- `s3-sensor-cloud/main/cloud` -> optional debug path only

