# HTTP v1 and MCP protocol

All application HTTP endpoints are under `/api/v1`. Every HTTP response includes `x-trace-id`; callers may send their own `x-trace-id` to correlate work.

## Device and data

- `GET /api/v1/devices`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history`
- `GET /api/v1/devices/{device_id}/history/bucketed`
- `GET /api/v1/devices/{device_id}/capabilities`
- `GET /api/v1/devices/{device_id}/events`
- `POST /api/v1/devices/{device_id}/images`
- `GET/POST /api/v1/devices/{device_id}/notifications`

History accepts UTC or offset-aware start/end timestamps. Report-oriented MCP history also accepts a bucket size and performs real aggregation; timezone offsets are converted to UTC rather than discarded.

## Commands

`POST /api/v1/devices/{device_id}/commands` validates the shared command catalog and returns `202` with a persisted command. It does not wait for MQTT or firmware.

Optional `idempotency_key` makes retries return the existing command. Query progress with `GET /api/v1/devices/{device_id}/commands/{command_id}`.

## Asynchronous AI

Create a run with `POST /api/v1/devices/{device_id}/ai/runs`:

```json
{"kind":"decision","trigger":"manual","goal":"检查当前环境"}
```

Kinds are `decision`, `report`, `vision`, and `patrol`. The create endpoint returns `202` immediately. List runs with `GET /api/v1/devices/{device_id}/ai/runs`, query one run with `GET /api/v1/devices/{device_id}/ai/runs/{run_id}`, and request cancellation with `POST /api/v1/devices/{device_id}/ai/runs/{run_id}/cancel`. States are `queued`, `running`, `waiting_model`, `calling_tool`, `waiting_device`, `succeeded`, `failed`, `cancelled`, and `skipped`.

Automation policy is persistent at `GET/PUT /api/v1/devices/{device_id}/automation-policy`. Patrol defaults to disabled, checks every 300 seconds when enabled, skips unchanged snapshots, and forces a model call after 3600 seconds.

## MCP

MCP is mounted at `/mcp` with Streamable HTTP using `mcp>=1.27,<2`. External access is disabled unless `AIOT_MCP_ENABLED=true` and both read/control tokens are configured.

Read token tools: `device_list`, `device_get_snapshot`, `device_get_history`, `device_list_events`, `device_get_capabilities`, and `device_get_command`.

Control token additionally exposes `device_execute_command` and `device_create_notification`. AI control is restricted to `window.*`, `led.*`, `voice.speak`, and `display.message`. Every tool returns:

```json
{"ok":true,"trace_id":"...","data":{},"error":null}
```

MCP tools call application use cases and never publish MQTT directly. The AI worker is the MCP host; the cloud model receives tool schemas and returns tool calls but never connects to `/mcp` itself.

`report` and `vision` Runs receive only read tools. Only `decision` and `patrol` Runs can see the AI-safe control tools. External read and control tokens must be non-empty and different; token comparisons are constant-time and the internal token is never returned in APIs or logs.

## Diagnostics

`GET /api/v1/diagnostics/overview` returns non-secret AI queue, outbox, realtime relay, Worker heartbeat, MCP switch and device-capability summaries. `GET /api/v1/diagnostics/traces/{trace_id}` returns one ordered `events[]` timeline spanning HTTP, AI, MCP, outbox, MQTT, firmware ACK and WebSocket delivery. The web console exposes the same views at `/diagnostics`.
