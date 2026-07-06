# AGENTS.md

## Command Rules

- Run PowerShell commands with PowerShell 7: `C:\Program Files\PowerShell\7\pwsh.exe`.
- This root directory is the workspace Git repository. Check nested reference
  repositories separately before using Git commands inside them.
- For a fresh checkout, prefer Espressif EIM/VS Code ESP-IDF v5.5.2 if present;
  otherwise use `scripts/setup-esp-idf.ps1`.

## New AIoT Mainline

- New architecture work belongs under `docs/`, `server/`, `web/`, `infra/`, and
  `firmware/esp32s3/`.
- Treat `docs/architecture.md`, `docs/protocol-mqtt.md`,
  `docs/protocol-http.md`, `docs/protocol-websocket.md`, and
  `docs/data-model.md` as the implementation contract.
- MQTT is the telemetry/control backbone. HTTP is for images, health checks, and
  frontend APIs.
- FastAPI `server/` owns LLM provider calls, JSON command validation, database
  writes, and WebSocket fanout.
- Next.js `web/` is a real-time control console, not a marketing landing page.
- Do not put LLM API keys, Wi-Fi credentials, MQTT credentials, or cloud tokens
  in firmware or frontend source.

## Firmware Build

- The current verified firmware path remains `s3-sensor-cloud/` until
  `firmware/esp32s3/` has migrated and passed hardware checks.
- Start firmware builds from the repository root, not from `s3-sensor-cloud/`.
- Use PowerShell 7 and run:
  `& 'C:\Users\lshap\Documents\Code\IoTCmpt\scripts\build.ps1'`.
- The build script selects the EIM ESP-IDF v5.5.2 environment from
  `C:\Espressif\tools\eim_idf.json` when available, then builds
  `s3-sensor-cloud` with build directory `build-esp32s3`.
- If the Codex sandbox blocks compiler process creation with
  `CreateProcess: Access is denied`, rerun the same `scripts\build.ps1`
  command with escalated permissions instead of changing SDK paths or invoking
  `idf.py` manually.

## VS Code ESP-IDF Notes

- `idf.currentSetup` must be the ESP-IDF SDK path, for example
  `C:\esp\v5.5.2\esp-idf`; do not set it to the EIM install id.
- `idf.eimIdfJsonPath` belongs in VS Code user/application settings and should
  point to `C:\Espressif\tools\eim_idf.json` when using EIM.
- CMake Tools prompts for a kit/compiler are not the primary ESP-IDF build path.
  ESP-IDF builds should go through the ESP-IDF extension or `idf.py`.
- It is acceptable to keep `cmake.configureOnOpen` disabled for this workspace.

## Project Focus

- Primary board: ESP32-S3-DevKitC-1.
- Primary framework: ESP-IDF v5.5.2. Prefer the EIM-managed setup from
  `C:\Espressif\tools\eim_idf.json` for builds. Treat
  `references/esp-idf-v5.5.2/` as a fallback/reference checkout; leave
  `references/esp-idf/` untouched unless the user explicitly asks.
- Competition direction: sensor + cloud control.
- Required competition capabilities: ESP32-S3 main controller, at least one
  fused sensor data source, at least one cloud LLM service, and either upstream
  sensor data processing or downstream LLM-issued device commands.
- Current firmware preserves teammate prototype features behind configuration
  switches: SHT30, TVOC301, LM393, ST7735, SG90, beeper, manual button, OV2640
  camera, sensor JSON upload, image upload, and pose-detection upload.

## Legacy Firmware Boundaries

- Product firmware is currently modularized under `s3-sensor-cloud/main/`.
- Keep `app_main` as an orchestrator: load config, initialize modules, and start
  tasks. Do not collapse hardware logic back into a large `main.c`.
- Keep local runtime state in `main/state/`; do not store manual override/window
  state inside sensor samples.
- `main/Kconfig` user-facing titles are intentionally Chinese. Do not rename
  `APP_*` config symbols because C code depends on those generated macros.
- During migration, reuse verified hardware modules but move new protocol work
  toward `firmware/esp32s3/`.

## Repository Layout

- ESP SDKs, docs, and reference repositories belong under `references/`.
- New deployable infrastructure belongs under `infra/` plus root
  `docker-compose.yml`.
- Do not commit secrets, Wi-Fi passwords, API tokens, or cloud credentials into
  source files.
- Do not copy build artifacts from teammate or local projects into this
  repository. Keep `build/`, `managed_components/`, `dependencies.lock`, local
  `sdkconfig`, binaries, uploaded images, and captured images untracked.
