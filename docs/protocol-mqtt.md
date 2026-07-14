# MQTT v2 protocol

MQTT is the telemetry and control backbone.

## Topics

- `devices/{device_id}/status`
- `devices/{device_id}/capabilities`
- `devices/{device_id}/telemetry`
- `devices/{device_id}/event`
- `devices/{device_id}/command`
- `devices/{device_id}/command_ack`
- `devices/{device_id}/log`

Status and capabilities are retained. Commands, ACKs and events use QoS 1. Telemetry normally uses QoS 0.

## Envelope

All messages use v2. The firmware no longer accepts the legacy bare command payload:

```json
{
  "schema_version": "2.0",
  "message_id": "msg-or-command-id",
  "trace_id": "end-to-end-trace-id",
  "device_id": "esp32s3-001",
  "occurred_at": "2026-07-14T08:00:00Z",
  "boot_id": "firmware-boot-id",
  "sequence": 42,
  "payload": {}
}
```

The JSON Schema is `contracts/mqtt-envelope.schema.json`. Firmware may send `occurred_at: null` before its clock is synchronized; `boot_id + sequence` still provides ordering within a boot.

## Capabilities

Firmware publishes `devices/{device_id}/capabilities` after connecting. Only compiled and initialized features are advertised. The server rejects a command that is absent from an advertised capability list.

`none` is not a command. A model decision with no action is stored in `ai_runs.output.action = null`.

## Command and ACK lifecycle

The server publishes a command only after persisting both the command and outbox record. Firmware validates capability, parameters, expiry, priority and safety interlocks.

```text
created -> queued -> published -> accepted -> executed
                                           -> rejected
                                           -> failed
                 -> expired / timed_out
```

Firmware first emits `accepted`, then a terminal ACK. The two ACKs have different `message_id` values while sharing the same `command_id` in their payload. Firmware stores recent terminal ACKs in NVS by `command_id`; redelivery returns the prior terminal result without executing hardware twice. The Gateway independently deduplicates inbound QoS 1 messages by device, topic and `message_id`.

If the Gateway has already marked a command `timed_out`, a later device ACK is recorded as `late_device_ack` for diagnosis but does not rewrite the authoritative timeout. The UI may show the late result beside the preserved timeout.

Errors use stable codes: `device_offline`, `unsupported_command`, `invalid_parameter`, `policy_denied`, `safety_interlock`, `expired`, `transport_error`, `device_rejected`, `timeout`.

The command catalog is `contracts/commands.json`. `display.message` is implemented by the firmware display module; unsupported build features are omitted from capabilities.
