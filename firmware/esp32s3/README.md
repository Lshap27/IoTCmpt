# ESP32-S3 Firmware

This directory is the ESP-IDF firmware mainline for the AIoT architecture.

## Behavior

- Publish retained online/offline status through MQTT.
- Publish periodic telemetry to `devices/{device_id}/telemetry`.
- Upload JPEG images to `POST /api/devices/{device_id}/images`.
- Subscribe to `devices/{device_id}/command`.
- Execute supported commands locally.
- Publish `devices/{device_id}/command_ack` after execution.

## Hardware Modules

- SHT30, TVOC301, and LM393 sampling.
- Local fusion rules.
- OV2640 camera.
- ST7735 display.
- SG90 servo.
- Active beeper.
- Manual button.
- Runtime control state.

## Configuration

The default configuration keeps Wi-Fi, MQTT, image upload, camera, display,
actuator, and button modules disabled so the project can compile without local
credentials or attached hardware.

Enable runtime features through `idf.py menuconfig` or local `sdkconfig`.
Do not commit Wi-Fi credentials, MQTT credentials, LLM keys, or local server
addresses.

## Build

From the repository root, use PowerShell 7:

```powershell
cd firmware\esp32s3
idf.py -B build build
```

## MQTT Behavior

When Wi-Fi and MQTT are enabled, the firmware:

- connects to the configured broker URI;
- publishes retained `online` status;
- publishes periodic telemetry from real or mock sensors;
- subscribes to `devices/{device_id}/command`;
- executes window, LED, manual alarm, runtime control-priority, smoke-silence,
  and server-encoded SYN6288 speech commands;
- publishes command ACKs with `executed`, `rejected`, or `failed` status.
