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
MediaPipe analysis. EfficientDet-Lite0 determines person presence independently
from BlazePose posture landmarks. The upload response does not wait for vision
inference; the structured result is delivered through `pose_result` WebSocket
messages and the latest device snapshot. A pose miss yields an unknown posture,
not an immediate absent-person result.

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

The server builds a text-only LLM request from the latest device snapshot,
current actuator/control-priority state, and a compact recent-telemetry trend. The
LLM must return a JSON decision. Commands outside the executable set
(`none`, `window.open`, `window.close`, `led.on`, `led.off`) are downgraded
to `none`.

Images are accepted only by `POST /api/devices/{device_id}/ai/analyze-image`.
That endpoint requires a capture no older than 15 seconds and never falls back
to text-only analysis. It returns structured `image_unavailable` or
`vision_unsupported` errors when appropriate.

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
  "speech": "",
  "scene_summary": "室内空气质量需要关注"
}
```

The same pipeline is also used by pose-driven lighting/sedentary workflows and
scheduled vision. Smoke and air-quality telemetry are handled by deterministic
firmware rules and do not start this AI pipeline.

## AI Health Report

```text
POST /api/devices/{device_id}/ai/report
```

Request body selects a real database window:

```json
{ "period": "hour" }
```

`period` accepts `hour`, `day`, or `week`. The server calculates coverage and
aggregate metrics from stored telemetry and events, then asks the configured
LLM for a structured report containing a risk level, 0–100 risk score,
headline, summary, anomalies, prioritized recommendations, and follow-up
checks. The response always includes the deterministic source metrics so the
model's conclusions remain auditable. A period with no telemetry returns 404.

`AIOT_LLM_ENDPOINT=mock` also supports reports, which keeps the report flow
testable without network access.

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
  "trigger_levels": ["alert"],
  "vision_capability": "unknown",
  "vision_interval_enabled": false,
  "vision_interval_effective": false,
  "vision_interval_seconds": 300,
  "sedentary_threshold_seconds": 7200,
  "smoke_silence_seconds": 60
}
```

`trigger_levels` is deprecated and retained only for compatibility; it no
longer starts an AI analysis. When enabled, autopilot still controls
pose-driven lighting/sedentary workflows and scheduled vision. Toggling
broadcasts an `autopilot` WebSocket event. The switch is in-memory; it resets
to `AIOT_AUTOPILOT_ENABLED` on server restart. The accepted sedentary reminder
range is 5–28800 seconds and its default remains 7200 seconds.

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

## Dorm Notification

```text
GET  /api/devices/{device_id}/notifications?limit=50
POST /api/devices/{device_id}/notifications
```

`GET` returns the newest persisted notifications first (`limit` 1–100). A
`POST` request contains trimmed text and an optional hardware voice request:

```json
{
  "content": "同学们请注意，今晚22:00将进行例行查寝。",
  "voice_broadcast": true
}
```

Text is limited to 500 characters. When `voice_broadcast=true`, its GB2312
representation must also fit the SYN6288 firmware limit of 220 bytes. The
server persists and broadcasts the text even when MQTT or voice playback is
unavailable. It creates a linked `voice.speak` command with
`parameter.gb2312_base64`; `voice_status` is one of `not_requested`,
`unavailable`, `pending`, `executed`, `rejected`, or `failed`.

`voice_status=unavailable` means no MQTT publish was confirmed. The API does
not claim that a browser has displayed or read the notification.
