# HTTP Protocol

The HTTP API is owned by `server/`. It serves dashboard reads, image upload,
manual command creation, and LLM-triggered analysis. MQTT remains the telemetry
and command transport for the device.

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

Returns latest telemetry, status, image, AI result, and command for one device.

## History

```text
GET /api/devices/{device_id}/history?limit=100
```

Returns recent telemetry samples ordered newest first.

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

## AI Analyze

```text
POST /api/devices/{device_id}/ai/analyze
```

The server builds an LLM request from latest telemetry and optional image
metadata. The LLM must return a JSON command. Invalid commands are downgraded to
`none`.

Response:

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

