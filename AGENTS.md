# AGENTS.md

## Command Rules
- Run PowerShell commands with PowerShell 7: `C:\Program Files\PowerShell\7\pwsh.exe`.
- This root directory is the workspace Git repository. Check nested reference repositories separately before using Git commands inside them.
- For a fresh checkout, prefer Espressif EIM/VS Code ESP-IDF v5.5.2 if present; otherwise use `scripts/setup-esp-idf.ps1`. Use `scripts/build.ps1` to build the firmware.

## VS Code ESP-IDF Notes
- `idf.currentSetup` must be the ESP-IDF SDK path, for example `C:\esp\v5.5.2\esp-idf`; do not set it to the EIM install id.
- `idf.eimIdfJsonPath` belongs in the VS Code user/application settings and should point to `C:\Espressif\tools\eim_idf.json` when using EIM.
- CMake Tools prompts for a kit/compiler are not the primary ESP-IDF build path. ESP-IDF builds should go through the ESP-IDF extension or `idf.py`, which supplies the cross compiler and CMake toolchain.
- It is acceptable to keep `cmake.configureOnOpen` disabled for this workspace so CMake Tools does not auto-configure the root folder.

## Project Focus
- Primary board: ESP32-S3-DevKitC-1.
- Primary framework: ESP-IDF v5.5.2. Prefer the EIM-managed setup from `C:\Espressif\tools\eim_idf.json` for builds. Treat `references/esp-idf-v5.5.2/` as a fallback/reference checkout; leave `references/esp-idf/` untouched unless the user explicitly asks.
- Competition direction: sensor + cloud control.
- Required competition capabilities: ESP32-S3 main controller, at least one fused sensor data source, at least one cloud LLM service, and either upstream sensor data processing or downstream LLM-issued device commands.

## Repository Layout
- ESP SDKs, docs, and reference repositories belong under `references/`.
- `references/esp-idf-v5.5.2/` is a fallback/reference SDK checkout. The active local tool environment is expected to come from EIM when available.
- Actual product firmware belongs under `s3-sensor-cloud/`.
- Do not commit secrets, Wi-Fi passwords, API tokens, or cloud credentials into source files.
