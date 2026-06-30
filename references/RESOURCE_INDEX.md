# ESP32-S3 Sensor + Cloud Resource Index

## Competition Requirements
- Original competition PDF is stored at `references/乐鑫命题和开发板类型情况说明.pdf`.
- Use one of the allowed Espressif chips; this project targets ESP32-S3.
- Fuse at least one sensor data source.
- Connect to at least one cloud large-model service.
- Support either device-to-model upstream perception data, or model-to-device downstream commands.
- Bonus directions relevant to this project: multi-source sensor fusion, low power, environment-triggered interaction, practical energy-saving/safety/service scenarios, and useful device form factor.

## ESP32-S3-DevKitC-1 Facts
- Board selected by the team: ESP32-S3-DevKitC-1.
- Module family: ESP32-S3-WROOM-1/1U.
- CPU: dual-core Xtensa LX7 up to 240 MHz.
- Wireless: 2.4 GHz Wi-Fi and Bluetooth 5 LE.
- Board I/O: most GPIO pins are broken out to side headers for jumper-wire or breadboard use.
- USB: dual Micro-USB paths for UART and native USB.
- AI support: PIE/vector-style acceleration instructions are available on ESP32-S3.

## Existing Local Resources
- `references/esp-idf/`: ESP-IDF source checkout. Currently left untouched even if it is on `master`.
- `references/esp-idf-v5.5.2/`: pinned ESP-IDF v5.5.2 SDK checkout for building the competition firmware without mutating `references/esp-idf/`.
- `references/esp-idf-zh_CN-v5.5.2/`: local Chinese ESP-IDF v5.5.2 documentation snapshot.
- `references/esp-iot-solution/`: ESP IoT Solution components and examples, especially sensors, display, touch, motor, USB, and utility examples.
- `references/esp-adf/`: ESP audio framework kept for future voice expansion, not used in the first sensor + cloud skeleton.

## Added Reference Repositories
| Directory | Source | Why it is here | First use |
| --- | --- | --- | --- |
| `references/esp-dev-kits` | https://github.com/espressif/esp-dev-kits.git | ESP development board documentation and examples, including ESP32-S3 board references. | Hardware pinout, board setup, flashing notes. |
| `references/esp-rainmaker` | https://github.com/espressif/esp-rainmaker.git | Espressif cloud control, provisioning, and device state examples. | Cloud control pattern and mobile/cloud managed device state. |
| `references/esp-now` | https://github.com/espressif/esp-now.git | Low-latency local wireless control and multi-node examples. | Optional sensor node expansion or local controller link. |
| `references/esp-protocols` | https://github.com/espressif/esp-protocols.git | Protocol components such as MQTT, WebSocket, modem, mDNS, and network helpers. | HTTP/MQTT/WebSocket reference implementations. |
| `references/esp-idf-template` | https://github.com/espressif/esp-idf-template.git | Minimal ESP-IDF project template. | Sanity reference for project layout. |

## Links Recorded, Not Cloned
- Marketplace, questionnaire, Bilibili, CSDN, and social/community links from the PDF are reference-only and should not be cloned.
- Cloud LLM documentation should be consulted online when choosing a provider: Volcengine AI Gateway, Baidu AI Studio, Aliyun Qwen, iFlytek Spark, and DeepSeek.
- Voice/vision/UI repositories such as `esp-sr`, `esp-who`, `esp-dl`, `esp-brookesia`, and `xiaozhi-esp32` are intentionally deferred because the current direction is sensor + cloud control.

## Notes
- `esp-dev-kits` may show case-collision warnings on Windows for unrelated examples. The S3 DevKitC-1 documentation remains usable.
- Because some repositories were cloned through an elevated Git process, Git may require a one-shot `-c safe.directory=<path>` when reading their metadata from the sandbox user.
