# ESP32-S3 Sensor + Cloud Resource Index

This directory is for optional local references only. Large SDKs, generated docs,
PDFs, and cloned example repositories should stay ignored and out of Git.

## Competition Requirements

- Target board: ESP32-S3-DevKitC-1.
- Main direction: sensor data plus cloud LLM control.
- Required capabilities:
  - ESP32-S3 main controller.
  - At least one fused sensor data source.
  - At least one cloud LLM service.
  - Either upstream sensor processing or downstream LLM-issued device commands.

## Optional Local Resources

These directories may exist on a developer machine, but are not required to be
tracked by this repository:

| Directory | Purpose |
| --- | --- |
| `references/esp-idf-v5.5.2/` | Fallback ESP-IDF SDK checkout when EIM is unavailable. |
| `references/esp-idf-zh_CN-v5.5.2/` | Local Chinese ESP-IDF documentation snapshot. |
| `references/esp-idf/` | Existing ESP-IDF checkout; leave untouched unless explicitly needed. |
| `references/esp-iot-solution/` | Sensor, display, touch, motor, USB, and utility examples. |
| `references/esp-adf/` | Audio framework for possible future voice expansion. |
| `references/esp-dev-kits/` | Board documentation and development kit examples. |
| `references/esp-rainmaker/` | Espressif cloud control and provisioning examples. |
| `references/esp-now/` | Optional local wireless node examples. |
| `references/esp-protocols/` | MQTT, WebSocket, mDNS, and protocol examples. |
| `references/esp-idf-template/` | Minimal ESP-IDF project template. |

## Notes

- Prefer EIM-managed ESP-IDF v5.5.2 on Windows when available.
- Use `scripts/setup-esp-idf.ps1` only when a local fallback SDK is needed.
- Do not commit PDFs, SDK checkouts, generated docs, binaries, or cloud secrets.
