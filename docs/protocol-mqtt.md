# MQTT Protocol

## Broker

- Default broker: EMQX.
- Default TCP listener: `1883`.
- Default dashboard: `http://localhost:18083`.
- MQTT payloads are UTF-8 JSON.

## Topic Contract

```text
devices/{device_id}/status
devices/{device_id}/telemetry
devices/{device_id}/event
devices/{device_id}/command
devices/{device_id}/command_ack
devices/{device_id}/log
```

`device_id` is stable across boots. The first demo device defaults to
`esp32s3-001`.

## QoS and Retain

- `status`: QoS 1, retain true. Firmware publishes `online` on boot and uses
  MQTT last will for `offline`.
- `telemetry`: QoS 0, retain false. It is periodic and can tolerate loss.
- `event`: QoS 1, retain false.
- `command`: QoS 1, retain false. Commands are persisted by the server before
  publish.
- `command_ack`: QoS 1, retain false.
- `log`: QoS 0, retain false.

## Telemetry Payload

```json
{
  "device_id": "esp32s3-001",
  "sampled_at": "2026-07-06T12:00:00Z",
  "sensors": {
    "temperature_c": 25.2,
    "humidity_percent": 69.2,
    "tvoc_ppb": 120,
    "hcho_ug_m3": 30,
    "eco2_ppm": 450,
    "light_is_dark": false,
    "smoke_detected": false
  },
  "state": {
    "window_open": false,
    "alarm_on": false,
    "manual_override": false,
    "led_on": false
  },
  "fusion": {
    "air_quality": "good",
    "recommend_open_window": false,
    "alarm_enabled": false,
    "reason": "空气质量正常"
  }
}
```

## Command Payload

```json
{
  "command_id": "cmd-20260706-0001",
  "type": "window.open",
  "parameter": {},
  "source": "llm",
  "confidence": 0.86,
  "reason": "室内空气质量较差，建议开窗",
  "created_at": "2026-07-06T12:00:03Z"
}
```

Allowed command types:

- `none`
- `window.open`
- `window.close`
- `alarm.on`
- `alarm.off`
- `led.on`
- `led.off`
- `display.message`

## Safety Events

MQ-2 transitions are published to `devices/{device_id}/event` with QoS 1:

```json
{"type":"smoke.detected","severity":"critical","message":"MQ-2 检测到烟雾"}
```

Clearing smoke publishes `smoke.cleared` with severity `info`. Repeated sensor
samples do not create repeated events; the event represents the transition.

## Command Ack Payload

```json
{
  "device_id": "esp32s3-001",
  "command_id": "cmd-20260706-0001",
  "status": "executed",
  "message": "window.open applied",
  "executed_at": "2026-07-06T12:00:05Z"
}
```

Allowed acknowledgement status values:

- `executed`
- `rejected`
- `failed`

## Error Handling

- Firmware ignores unsupported commands and publishes `command_ack` with
  `status=rejected`.
- Server validates all LLM-generated commands before publishing.
- Server stores malformed MQTT payloads as events when possible, then broadcasts
  an error event for the dashboard.
- Reconnect behavior is idempotent: the retained status topic reflects current
  online/offline state, while commands are never retained.
