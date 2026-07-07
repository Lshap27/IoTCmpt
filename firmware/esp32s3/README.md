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

This directory now contains a minimal ESP-IDF project shell for the new
mainline. It does not migrate the verified hardware drivers yet.

The default configuration keeps Wi-Fi and MQTT disabled, so the project can
compile without local credentials. Enable `APP_WIFI_ENABLED` and
`APP_MQTT_ENABLED` through `idf.py menuconfig` before hardware MQTT bring-up.

## Build

From the repository root, use PowerShell 7:

```powershell
& .\scripts\build-firmware-mainline.ps1
```

The current verified production firmware still lives in `s3-sensor-cloud/`.
Use the existing root build entry for legacy regression:

```powershell
& .\scripts\build.ps1
```

## MQTT Shell Behavior

When Wi-Fi and MQTT are enabled, the shell:

- connects to the configured broker URI;
- publishes retained `online` status;
- publishes periodic mock telemetry;
- subscribes to `devices/{device_id}/command`;
- logs received command payloads;
- publishes `command_ack` with mock execution status.
