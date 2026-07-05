# ESP32-S3 Sensor Cloud

ESP-IDF firmware for the ESP32-S3-DevKitC-1 competition direction: sensor
sampling, local fusion, cloud LLM exchange, and downstream device commands.

## Current Architecture

- `main/config`: loads Kconfig/sdkconfig values into `app_config_t`.
- `main/sensors`: exposes `sensor_sample_t` through `sensors_init()` and `sensors_read()`.
- `main/fusion`: turns sensor samples into `fusion_state_t`.
- `main/cloud`: sends state to an HTTP-compatible cloud LLM endpoint and parses commands.
- `main/commands`: validates and applies supported downstream commands.
- `main/net`: owns Wi-Fi station connection setup.

The default configuration uses mock sensor samples and keeps Wi-Fi/cloud disabled,
so the firmware can compile and boot without external hardware or secrets.

## Configuration

Run menuconfig inside the ESP-IDF environment to enable real connectivity:

```powershell
idf.py menuconfig
```

Relevant options are under `S3 Sensor Cloud`:

- `APP_SENSOR_MOCK_ENABLED`
- `APP_SENSOR_INTERVAL_MS`
- `APP_WIFI_ENABLED`
- `APP_WIFI_SSID`
- `APP_WIFI_PASSWORD`
- `APP_CLOUD_ENABLED`
- `APP_CLOUD_ENDPOINT`
- `APP_CLOUD_MODEL`
- `APP_CLOUD_TOKEN`

Do not commit local `sdkconfig` files containing Wi-Fi or cloud credentials.

## Build

From the workspace root:

```powershell
.\scripts\build.ps1
```

Manual ESP-IDF flow:

```powershell
idf.py set-target esp32s3
idf.py build
```

Flash only after confirming the serial port and board connection:

```powershell
idf.py -p COMx flash monitor
```

## Next Steps

- Replace the mock sensor layer with SHT30, TVOC301, and LM393 drivers.
- Add an actuator implementation for the validated command set.
- Lock the cloud response schema for the selected LLM provider.
- Add host-side or component tests for fusion rules and command parsing.
