# WebSocket v2 protocol

The browser first reads authoritative state through HTTP, then applies WebSocket events to the TanStack Query cache. Reconnection always triggers an HTTP snapshot refresh.

Endpoint: `WS /ws/devices/{device_id}`.

```json
{
  "schema_version": "2.0",
  "event_id": "evt-...",
  "trace_id": "trace-...",
  "device_id": "esp32s3-001",
  "occurred_at": "2026-07-14T08:00:00Z",
  "type": "command.status_changed",
  "payload": {}
}
```

Primary discriminants:

- `device.status_changed`
- `telemetry.received`
- `perception.updated` (`kind`: `image`, `pose`, `event`, or `log`)
- `command.status_changed`
- `ai.run.status_changed`
- `automation.policy.changed`
- `notification.created`
- `device.capabilities_changed`
- `system.error`

The generated `WsMessage` discriminated union is exported with OpenAPI. `web/src/lib/ws-dispatcher.ts` is a pure reducer that writes only to Query Cache keys. A bounded per-device `event_id` cache discards relay retries, duplicate telemetry replaces rather than appends a point, and terminal command status is irreversible. AI events update both detail and list caches. Reconnection invalidates the device snapshot, command list, capability list, AI Run list and automation policy before resuming live updates.
