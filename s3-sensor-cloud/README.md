# ESP32-S3 Sensor Cloud

ESP32-S3-DevKitC-1 firmware skeleton for the 2026 IoT competition direction: sensor data plus cloud large-model control.

## Goals
- Collect and fuse sensor data on ESP32-S3.
- Send non-audio/video perception data to a cloud LLM provider.
- Receive compact downstream commands and apply them to local device state.
- Keep provider choice replaceable: Volcengine AI Gateway, Qwen, iFlytek Spark, DeepSeek, Baidu AI Studio, or another HTTP-compatible service.

## Current Skeleton
- Initializes NVS and a status GPIO placeholder.
- Provides a fake sensor sample source for buildable structure.
- Builds a JSON payload with cJSON.
- Contains a placeholder cloud exchange function intended to be replaced with `esp_http_client` or MQTT.
- Applies simple placeholder commands: `led:on` and `led:off`.

## Build
Run from this directory after loading ESP-IDF environment:

```powershell
. ..\references\esp-idf-v5.5.2\export.ps1
idf.py set-target esp32s3
idf.py build
```

Flash only after confirming the serial port:

```powershell
idf.py -p COMx flash monitor
```

## Next Development Steps
- Choose the actual sensor set and replace `sensor_read_placeholder()`.
- Add Wi-Fi provisioning or local Wi-Fi config.
- Add menuconfig or config-file support for endpoint, model, and token.
- Replace `cloud_llm_exchange_placeholder()` with HTTP/MQTT implementation.
- Define a strict command schema for LLM responses.
