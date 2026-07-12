# HTTP Protocol

The HTTP API is owned by `server/`. It serves dashboard reads, image upload,
manual command creation, and LLM-triggered analysis. MQTT remains the telemetry
and command transport for the device.

The machine-readable contract is `server/openapi.json`, exported from the
FastAPI app by `server/scripts/export_openapi.py`. The frontend client is
generated from it (`pnpm codegen` in `web/`), and CI fails on drift. This
document is the human-readable companion.

## Health

```text
GET /health
```

Response:

```json
{
  "status": "ok",
  "service": "aiot-gateway"
}
```

## Device Listing

```text
GET /api/devices
```

Returns known devices with latest online state.

## Latest State

```text
GET /api/devices/{device_id}/latest
```

Returns latest telemetry, status, image, AI result, command, and the autopilot
switch state (`autopilot.enabled`) for one device.

## History

```text
GET /api/devices/{device_id}/history?limit=100
```

Returns recent telemetry samples ordered newest first.

## Bucketed History

```text
GET /api/devices/{device_id}/history/bucketed?bucket=60&limit=200
```

Returns time-bucketed telemetry aggregates (TimescaleDB `time_bucket`),
ordered newest bucket first. `bucket` is the window size in seconds
(10–86400, default 60); `limit` caps the number of buckets (1–2000, default
200). Numeric sensor fields are averaged; boolean state fields are `true`
when any sample in the bucket is `true` (`bool_or`); `air_quality` is the
worst level seen in the bucket; `sample_count` reports how many raw samples
each bucket aggregates. Requires PostgreSQL/TimescaleDB; on other backends
the endpoint returns `400`.

Response item:

```json
{
  "bucket": "2026-07-08T05:47:00",
  "temperature_c": 27.0,
  "humidity_percent": 60.0,
  "tvoc_ppb": 120.0,
  "hcho_ug_m3": null,
  "eco2_ppm": 600.0,
  "window_open": false,
  "alarm_on": false,
  "air_quality": "good",
  "sample_count": 5
}
```

## Image Upload

```text
POST /api/devices/{device_id}/images
Content-Type: multipart/form-data
```

Form field:

- `file`: JPEG image.

Response:

```json
{
  "id": 1,
  "device_id": "esp32s3-001",
  "url": "http://localhost:8000/uploads/esp32s3-001/image.jpg",
  "created_at": "2026-07-06T12:00:00Z"
}
```

When `AIOT_POSE_ENABLED=true`, a successful upload is queued for local
MediaPipe analysis. The upload response does not wait for pose inference; the
result is delivered through `pose_result` WebSocket messages and the latest
device snapshot.

## Pose and Safety Events

```text
POST /api/devices/{device_id}/pose/analyze
GET  /api/devices/{device_id}/events?type=smoke.detected
POST /api/devices/{device_id}/events/{event_id}/ack
```

Pose analysis always uses the latest original capture and returns `202` when
queued. Event acknowledgement updates the ledger only; it never silences an
active device-side smoke alarm.

## AI Analyze

```text
POST /api/devices/{device_id}/ai/analyze
```

The server builds an LLM request from the latest device snapshot, a compact
recent-telemetry trend, and — when the newest uploaded image is fresh enough —
the JPEG itself (OpenAI-compatible vision message with a base64 data URL). The
LLM must return a JSON decision. Commands outside the executable set
(`none`, `window.open`, `window.close`, `alarm.on`, `alarm.off`, `led.on`, `led.off`) are downgraded
to `none`.

The generated command is always persisted. It is published to MQTT only when
`type != "none"` and `confidence >= AIOT_AUTOPILOT_MIN_CONFIDENCE`; otherwise it
stays `pending` as a suggestion.

Setting `AIOT_LLM_ENDPOINT=mock` enables a deterministic offline decision mode
for demos and tests.

Response:

```json
{
  "command": {
    "command_id": "cmd-1a2b3c4d5e6f7a8b",
    "type": "window.open",
    "parameter": {},
    "source": "llm",
    "confidence": 0.86,
    "reason": "室内空气质量较差，建议开窗",
    "status": "published",
    "created_at": "2026-07-06T12:00:03Z",
    "published_at": "2026-07-06T12:00:03Z",
    "executed_at": null
  },
  "risk_level": "medium",
  "confidence": 0.86,
  "reason": "室内空气质量较差，建议开窗",
  "model": "qwen-vl-plus",
  "trigger": "manual",
  "published": true,
  "image_attached": true
}
```

The same pipeline runs automatically when telemetry matches the autopilot
trigger rules (see below); those results carry `trigger = "auto:<rule>"`.

## Autopilot

```text
GET /api/devices/{device_id}/autopilot
PUT /api/devices/{device_id}/autopilot
```

`PUT` request:

```json
{
  "enabled": true
}
```

Response (both methods):

```json
{
  "device_id": "esp32s3-001",
  "enabled": true,
  "cooldown_seconds": 120,
  "min_confidence": 0.6,
  "trigger_levels": ["alert"]
}
```

When enabled, telemetry whose `fusion.air_quality` is in `trigger_levels` (or
whose `fusion.alarm_enabled` is true) starts an AI analysis automatically,
subject to the per-device cooldown. Toggling broadcasts an `autopilot`
WebSocket event. The switch is in-memory; it resets to
`AIOT_AUTOPILOT_ENABLED` on server restart.

## Manual Command

```text
POST /api/devices/{device_id}/commands
```

Request:

```json
{
  "type": "alarm.on",
  "parameter": {},
  "reason": "manual dashboard command"
}
```

The server stores the command and publishes it to
`devices/{device_id}/command`.
