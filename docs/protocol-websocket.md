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

The envelope types are defined as the `WsMessage` discriminated union in
`server/app/schemas.py` and embedded into `server/openapi.json` by the export
script, so the frontend consumes generated types and narrows the payload by
switching on `type` (`web/src/lib/ws-dispatcher.ts`).

## Event Types

- `status`: device online/offline and broker state.
- `telemetry`: latest sensor and fusion data.
- `event`: device or server event, including autopilot trigger records
  (`payload.type = "autopilot"`).
- `image`: image metadata after upload.
- `pose_result`: local MediaPipe result and optional annotated image metadata.
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
    "trigger": "manual",
    "published": true,
    "speech": "",
    "scene_summary": "窗户已打开但空气质量仍在恶化"
  }
  ```

  `published=false` means the confidence gate held the command back; it is
  stored as a suggestion with `status=pending` and never sent to the device.
- `command`: command created or published.
- `command_ack`: command acknowledgement from firmware.
- `notification`: a persisted dorm notification. Its payload matches the
  HTTP `NotificationOut` model and includes the linked voice command status.
- `autopilot`: autopilot switch state changed. Payload mirrors
  `GET /api/devices/{device_id}/autopilot`.
- `log`: device log line.
- `error`: malformed payload, rejected command, or service degradation.

`event` payloads for `smoke.detected` and `smoke.cleared` include the
persisted event `id`, so the dashboard can acknowledge the exact ledger entry.
`pose_result` keeps the compatibility fields `human_present`, `label`, and
`confidence`, and adds independent presence/posture fields:
`presence_confidence`, `presence_source`, `body_coverage`, `seated_state`,
`posture_code`, `posture_issues`, `posture_confidence`, and `posture_fresh`.
Image links remain in `source_image_url` and `annotated_image_url`. A detected
person may therefore have `posture_code=unknown`; clients must not interpret
that as an empty room.

## Client Behavior

- On page load, the client calls `GET /api/devices/{device_id}/latest` and
  `GET /api/devices/{device_id}/history`; notification-capable pages also call
  `GET /api/devices/{device_id}/notifications`.
- After that, the WebSocket stream updates the visible dashboard state.
- If the socket disconnects, the UI shows a degraded live state and retries.
- After reconnect, the client refetches notifications so messages created
  during the outage are not lost.
- The frontend never connects directly to PostgreSQL or MQTT.
