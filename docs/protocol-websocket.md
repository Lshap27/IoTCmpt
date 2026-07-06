# WebSocket Protocol

The frontend connects to:

```text
WS /ws/devices/{device_id}
```

The server sends JSON envelopes. Every envelope has:

```json
{
  "type": "telemetry",
  "device_id": "esp32s3-001",
  "occurred_at": "2026-07-06T12:00:00Z",
  "payload": {}
}
```

## Event Types

- `status`: device online/offline and broker state.
- `telemetry`: latest sensor and fusion data.
- `event`: device or server event.
- `image`: image metadata after upload.
- `ai_result`: LLM analysis result.
- `command`: command created or published.
- `command_ack`: command acknowledgement from firmware.
- `log`: device log line.
- `error`: malformed payload, rejected command, or service degradation.

## Client Behavior

- On page load, the client calls `GET /api/devices/{device_id}/latest` and
  `GET /api/devices/{device_id}/history`.
- After that, the WebSocket stream updates the visible dashboard state.
- If the socket disconnects, the UI shows a degraded live state and retries.
- The frontend never connects directly to PostgreSQL or MQTT.

