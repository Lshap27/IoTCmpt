# Data Model

The gateway stores normalized records while preserving the raw JSON payload
for debugging. The schema is managed by Alembic migrations
(`server/alembic/versions/`); `AIOT_AUTO_CREATE_TABLES` stays `false` when
migrations own the schema.

## device

- `id`: database id.
- `device_id`: stable public device id, for example `esp32s3-001`.
- `display_name`: human-friendly name.
- `status`: `online`, `offline`, or `unknown`.
- `last_seen_at`: latest MQTT or HTTP contact time.
- `metadata`: JSON.

## telemetry

On PostgreSQL, `telemetry` is a TimescaleDB hypertable partitioned on
`sampled_at` (migration `0002`), with primary key `(id, sampled_at)` as the
hypertable requires. The ORM keeps the single-column `id` so SQLite test
databases still autoincrement. Time-bucketed aggregates for the dashboard are
served by `GET /api/devices/{device_id}/history/bucketed` using
`time_bucket`. Bucket responses include averages for continuous sensor values,
temperature minima/maxima, maximum eCO2, latest LM393/smoke/actuator states,
and the number of persisted samples represented by each bucket. Reports use
these aggregates without inventing samples for missing periods.

- `id`
- `device_id`
- `sampled_at`
- `temperature_c`
- `humidity_percent`
- `tvoc_ppb`
- `hcho_ug_m3`
- `eco2_ppm`
- `light_is_dark`
- `smoke_detected`
- `window_open`
- `alarm_on`
- `manual_override`
- `manual_window_override`
- `manual_led_override`
- `control_priority`
- `smoke_silenced`
- `led_on`
- `air_quality`
- `recommend_open_window`
- `alarm_enabled`
- `reason`
- `raw_payload`
- `created_at`

## event

- `id`
- `device_id`
- `type`
- `severity`
- `message`
- `raw_payload`
- `created_at`
- `acknowledged_at`

## command

- `id`
- `command_id`
- `device_id`
- `type`
- `parameter`
- `source`
- `confidence`
- `reason`
- `status`: `pending`, `published`, `executed`, `rejected`, or `failed`.
- `raw_payload`
- `created_at`
- `published_at`
- `executed_at`

## ai_result

- `id`
- `device_id`
- `command_id`
- `summary`
- `risk_level`
- `model`
- `confidence`
- `reason`
- `speech`
- `scene_summary`
- `raw_payload`
- `created_at`

## image_asset

- `id`
- `device_id`
- `filename`
- `url`
- `content_type`
- `size_bytes`
- `kind`: `capture` or `pose_annotated`.
- `created_at`

Image retention is configured with `AIOT_MAX_IMAGES_PER_DEVICE` (default 100).
After a new capture or annotated pose image is stored, the gateway removes the
oldest excess image records, their files, and pose results that reference those
expired assets.

## pose_result

- `device_id`
- `source_image_id`
- `annotated_image_id`
- `human_present`
- `label`
- `confidence`
- `raw_payload`
- `created_at`
