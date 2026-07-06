# ESP32-S3 Firmware Mainline

This directory is the target firmware mainline for the AIoT architecture.

The current verified implementation still lives in `s3-sensor-cloud/`. During
migration, copy or move hardware modules here only after their behavior is
covered by the new MQTT/HTTP protocol contract.

## Target Behavior

- Publish retained online/offline status through MQTT.
- Publish periodic telemetry to `devices/{device_id}/telemetry`.
- Upload JPEG images to `POST /api/devices/{device_id}/images`.
- Subscribe to `devices/{device_id}/command`.
- Execute supported commands locally.
- Publish `devices/{device_id}/command_ack` after execution.

## Reused Hardware Modules

The migration should preserve the known-good modules from `s3-sensor-cloud/`:

- SHT30, TVOC301, and LM393 sampling.
- Local fusion rules.
- OV2640 camera.
- ST7735 display.
- SG90 servo.
- Active beeper.
- Manual button.
- Runtime control state.

## Current Status

Skeleton only. Use `s3-sensor-cloud/` for builds and hardware flashing until
this mainline has an ESP-IDF project and passes the hardware bring-up checklist.

