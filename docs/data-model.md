# Data Model

The v2 architecture adds persistent device capability/twin, command audit, transactional outbox, AI-run, MCP-tool-call, automation-policy and AI-report tables. Migration `0006_architecture_v2.py` introduces the base tables; `0007_reliable_worker_cutover.py` adds leases, realtime/trace events and worker heartbeats while migrating legacy AI history; `0008_reliability_fencing.py` adds per-claim lease tokens and MQTT inbox idempotency.

| Table | Purpose |
| --- | --- |
| `device_capabilities` | last retained capability document per device |
| `device_twins` | desired and reported state, with update timestamps |
| `command_events` | append-only command state transitions keyed by `trace_id` |
| `outbox_messages` | recoverable MQTT publication queue |
| `ai_runs` | persistent asynchronous AI task state and output |
| `ai_tool_calls` | MCP tool arguments, result and error audit |
| `automation_policies` | per-device event/patrol settings and fingerprints |
| `ai_reports` | report output linked to its AI run |
| `realtime_events` | transactional Worker-to-Gateway WebSocket relay |
| `trace_events` | ordered cross-component diagnostic timeline |
| `runtime_instances` | worker heartbeat and metadata |
| `runtime_leases` | singleton patrol scheduler election |
| `mqtt_inbox_messages` | QoS 1 input deduplication by device/topic/message ID |

`ai_runs`, `outbox_messages` and `realtime_events` carry `lease_owner` and a unique per-claim `lease_token`. A Worker or relay may renew or finish only while both still match. `ai_tool_calls` uses stable call identifiers, and reports are upserted by Run, so a recovered job cannot duplicate the audit row or report.

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
served by `GET /api/v1/devices/{device_id}/history/bucketed` using
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

`human_present`, `label`, and `confidence` remain the compatibility fields.
Structured presence and posture data is stored in `raw_payload` and exposed by
the HTTP/WebSocket serializers as `presence_confidence`, `presence_source`,
`body_coverage`, `seated_state`, `posture_code`, `posture_issues`,
`posture_confidence`, and `posture_fresh`. This keeps existing rows readable
without a schema migration while separating occupancy from posture quality.
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
- `status`: `created`, `queued`, `published`, `accepted`, `executed`, `rejected`, `failed`, `expired`, or `timed_out`.
- `raw_payload`
- `created_at`
- `published_at`
- `executed_at`

Idempotency is scoped by `(device_id, source, idempotency_key)`. A late device ACK after `timed_out` is stored as diagnostic detail without changing the main terminal status.

## ai_run

AI output, retries, cancellation requests, worker ownership and lease timestamps live in `ai_runs`. Legacy `ai_results` rows are converted into completed legacy runs by migration `0007`; the old table is then removed.

## image_asset

- `id`
- `device_id`
- `filename`
- `url`
- `content_type`
- `size_bytes`
- `kind`: `capture` or `pose_annotated`.
- `created_at`

## notification

- `id`
- `device_id`
- `content`: persisted text shown on the dorm dashboard.
- `voice_requested`: whether the sender requested SYN6288 playback.
- `voice_command_id`: nullable link to the generated `voice.speak` command.
- `created_at`

The user-facing `voice_status` is derived from the linked command rather than
duplicated in this table. Text delivery remains available when the command is
unpublished, rejected, or failed.

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
