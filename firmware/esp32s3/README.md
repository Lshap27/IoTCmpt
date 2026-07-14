# ESP32-S3 Firmware

This directory is the ESP-IDF 5.5.2 firmware mainline. Firmware owns sensing,
execution, local real-time rules, and final safety vetoes; it never connects to
a cloud LLM.

## Runtime behavior

- Publish retained online status and capabilities after MQTT connection.
- Publish MQTT v2 telemetry, events, and logs.
- Upload JPEG images to `POST /api/v1/devices/{device_id}/images`.
- Accept only MQTT v2 commands and validate version, device/command ID, source,
  parameters, TTL, capability, priority, and safety interlocks.
- Reply `accepted` before independent execution, then `executed`, `rejected`,
  or `failed`.
- Persist the last 16 terminal ACKs by `command_id` in NVS so QoS 1 redelivery
  replays a result without repeating hardware work.
- Synchronize time with SNTP and enforce `expires_at` when the clock is trusted.

## Hardware and local rules

SHT30, TVOC301, and LM393 feed local air fusion. Automatic-first mode opens a
window for ventilation but does not close it automatically after recovery.
Smoke alarm logic never waits for the server or LLM; silence only masks the
smoke source temporarily. OV2640, ST7735, SG90, beeper, SYN6288, and buttons are
enabled per build configuration. Manual window targets reach the actuator loop,
and manual-first/safety rules can reject AI or external-MCP commands.

Capabilities depend on the actual module: window/alarm, LED, display, and voice
are independent. Parameter, policy, and safety refusals return `rejected` with
stable codes; only execution faults return `failed`.

## Configuration and preflight

The safe default disables networking, image upload, physical modules, and mock
sensor data. Enable real features through `idf.py menuconfig` or local
`sdkconfig`. Never commit `sdkconfig`, credentials, or machine-specific URLs.

Startup preflight rejects duplicate GPIOs, native-USB GPIO19/20 conflicts, and
GPIO35-37 under octal-PSRAM configurations. Unknown board variants still need
manual review. Keep the current OV2640 PWDN-only `pin_xclk=-1` design unless
physical evidence justifies XCLK.

`configs/full-hardware.defaults` is compile coverage, not a flash-ready demo
profile; Wi-Fi, MQTT, and image upload remain disabled there.

## Build

```powershell
cd firmware\esp32s3
idf.py -B build build
```

In this validation, the safe image was about `0xdf4a0` with roughly 40% of its
application partition free; the full compile profile was about `0x10d980` with
roughly 28% free. Treat current build output as authoritative as sizes evolve.

## Physical validation boundary

Compilation and the behavior simulator do not replace a board test. This run
had no physical ESP32-S3, so USB/serial, power, real GPIO, PSRAM, OV2640 timing,
display, voice, sensor levels, and mechanical actuator movement remain
unverified. Complete `docs/hardware-loop.md` before claiming board readiness.
