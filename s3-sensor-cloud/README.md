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
Run from the workspace root:

```powershell
.\scripts\build.ps1
```

The script prefers the EIM-managed ESP-IDF v5.5.2 setup and falls back to the local reference checkout if EIM is not available.

Flash only after confirming the serial port:

```powershell
idf.py -p COMx flash monitor
```

## VS Code Notes
- The ESP-IDF extension should use `C:\esp\v5.5.2\esp-idf` as `idf.currentSetup`.
- If CMake Tools asks for a kit/compiler, it can usually be ignored for ESP-IDF work. The ESP-IDF extension and `idf.py` provide the CMake toolchain and ESP32-S3 cross compiler.
- This workspace keeps `cmake.configureOnOpen` disabled to avoid CMake Tools auto-configuring the repository root.

## Next Development Steps
- Choose the actual sensor set and replace `sensor_read_placeholder()`.
- Add Wi-Fi provisioning or local Wi-Fi config.
- Add menuconfig or config-file support for endpoint, model, and token.
- Replace `cloud_llm_exchange_placeholder()` with HTTP/MQTT implementation.
- Define a strict command schema for LLM responses.
