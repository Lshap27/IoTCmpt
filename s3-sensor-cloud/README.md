# ESP32-S3 Sensor Cloud

ESP-IDF firmware for the ESP32-S3-DevKitC-1 competition direction: sensor
sampling, local fusion, ordinary backend upload, cloud LLM exchange, and
downstream device commands.

## Current Architecture

- `main/config`: loads Kconfig/sdkconfig values into `app_config_t`.
- `main/sensors`: reads SHT30, TVOC301, and LM393, or emits mock samples.
- `main/fusion`: turns samples into air quality, window, and alarm decisions.
- `main/backend`: uploads sensor JSON and camera JPEG multipart payloads.
- `main/cloud`: sends state to an HTTP-compatible cloud LLM endpoint and parses commands.
- `main/actuators`: drives the SG90 window servo and active beeper.
- `main/inputs`: handles the manual toggle button.
- `main/display`: renders status bars on the ST7735 TFT.
- `main/camera`: initializes OV2640 and captures QVGA JPEG frames.
- `main/state`: stores local manual override, window, and alarm state.

The default configuration is deliberately safe: mock sensor samples are enabled,
while Wi-Fi, backend upload, cloud, camera, display, actuator, and button modules
are disabled. This lets the firmware build and boot without hardware or secrets.

## Configuration

Run menuconfig inside the ESP-IDF environment:

```powershell
idf.py menuconfig
```

Useful options are under `S3 传感器云端控制`:

- Connectivity: `APP_WIFI_ENABLED`, `APP_WIFI_SSID`, `APP_WIFI_PASSWORD`.
- Cloud LLM: `APP_CLOUD_ENABLED`, `APP_CLOUD_ENDPOINT`, `APP_CLOUD_MODEL`, `APP_CLOUD_TOKEN`.
- Backend upload: `APP_BACKEND_ENABLED`, `APP_SENSOR_UPLOAD_URL`, `APP_IMAGE_UPLOAD_URL`, `APP_POSE_UPLOAD_URL`.
- Feature modules: `APP_CAMERA_ENABLED`, `APP_DISPLAY_ENABLED`, `APP_ACTUATOR_ENABLED`, `APP_BUTTON_ENABLED`.
- Sensors and pins: SHT30, TVOC301, LM393, SG90, beeper, button, TFT, and OV2640 GPIO options.

Do not commit local `sdkconfig` files containing Wi-Fi passwords, backend URLs,
cloud tokens, or model credentials.

To recover the teammate prototype behavior on a local board, configure at least:

```text
APP_SENSOR_MOCK_ENABLED=n
APP_WIFI_ENABLED=y
APP_BACKEND_ENABLED=y
APP_CAMERA_ENABLED=y
APP_DISPLAY_ENABLED=y
APP_ACTUATOR_ENABLED=y
APP_BUTTON_ENABLED=y
```

Then fill in local-only values:

```text
APP_WIFI_SSID=<your Wi-Fi>
APP_WIFI_PASSWORD=<your Wi-Fi password>
APP_SENSOR_UPLOAD_URL=http://<server-ip>:8000/api/upload_sensor
APP_IMAGE_UPLOAD_URL=http://<server-ip>:8000/api/upload_image
APP_POSE_UPLOAD_URL=http://<server-ip>:8000/api/detect_pose
```

Cloud LLM settings are optional and separate from ordinary backend upload.
Enable `APP_CLOUD_ENABLED` only after choosing a real LLM provider and response schema.

## Hardware Notes

The OV2640 camera defaults preserve the teammate-verified setup: QVGA JPEG,
10 MHz XCLK, one DRAM framebuffer, and the DVP pin map from the prototype.

The prototype used GPIO10 for both OV2640 XCLK and TFT CS. The modular default
keeps camera XCLK on GPIO10 and sets `APP_TFT_CS_GPIO=5`. Change this in
menuconfig to match the actual display wiring before enabling both modules.

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

## Bring-Up Order

1. Build and boot with defaults.
2. Disable `APP_SENSOR_MOCK_ENABLED` and verify SHT30/TVOC301/LM393 logs.
3. Enable Wi-Fi and backend sensor upload with local URLs in `sdkconfig`.
4. Enable actuator and button, then verify manual window toggle.
5. Enable display after confirming TFT CS does not conflict with camera XCLK.
6. Enable camera and image/pose upload after backend endpoints are reachable.

## Development Notes

- Keep `main/main.c` focused on orchestration and task startup.
- Add or change hardware behavior in its module, not in `main.c`.
- Keep `main/backend` for ordinary HTTP uploads and `main/cloud` for LLM exchange.
- Keep `APP_*` Kconfig symbol names stable even though the visible labels are Chinese.
- Do not reintroduce hard-coded Wi-Fi credentials, backend IPs, or cloud tokens.
