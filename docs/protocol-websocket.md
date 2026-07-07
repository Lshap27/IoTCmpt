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
- `event`: device or server event, including autopilot trigger records
  (`payload.type = "autopilot"`).
- `image`: image metadata after upload.
- `ai_analyzing`: an AI analysis has started. Payload contains the trigger
  (`manual` or `auto:<rule>`); the dashboard shows a "thinking" state until the
  matching `ai_result` arrives.
- `ai_result`: LLM analysis result. Payload:

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
    "trigger": "auto:air_quality=alert",
    "published": true,
    "image_attached": true
  }
  ```

  `published=false` means the confidence gate held the command back; it is
  stored as a suggestion with `status=pending` and never sent to the device.
- `command`: command created or published.
- `command_ack`: command acknowledgement from firmware.
- `autopilot`: autopilot switch state changed. Payload mirrors
  `GET /api/devices/{device_id}/autopilot`.
- `log`: device log line.
- `error`: malformed payload, rejected command, or service degradation.

## Client Behavior

- On page load, the client calls `GET /api/devices/{device_id}/latest` and
  `GET /api/devices/{device_id}/history`.
- After that, the WebSocket stream updates the visible dashboard state.
- If the socket disconnects, the UI shows a degraded live state and retries.
- The frontend never connects directly to PostgreSQL or MQTT.

