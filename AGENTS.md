# AGENTS.md

## Command Rules
- Run PowerShell commands with PowerShell 7: `C:\Program Files\PowerShell\7\pwsh.exe`.
- This root directory is the workspace Git repository. Check nested reference repositories separately before using Git commands inside them.
- For a fresh checkout, use `scripts/setup-esp-idf.ps1` to install ESP-IDF tools and `scripts/build.ps1` to build the firmware.

## Project Focus
- Primary board: ESP32-S3-DevKitC-1.
- Primary framework: ESP-IDF v5.5.2. Prefer the local `references/esp-idf-v5.5.2/` checkout for builds; leave `references/esp-idf/` untouched unless the user explicitly asks.
- Competition direction: sensor + cloud control.
- Required competition capabilities: ESP32-S3 main controller, at least one fused sensor data source, at least one cloud LLM service, and either upstream sensor data processing or downstream LLM-issued device commands.

## Repository Layout
- ESP SDKs, docs, and reference repositories belong under `references/`.
- `references/esp-idf-v5.5.2/` is the pinned SDK checkout for competition firmware verification.
- Actual product firmware belongs under `s3-sensor-cloud/`.
- Do not commit secrets, Wi-Fi passwords, API tokens, or cloud credentials into source files.
