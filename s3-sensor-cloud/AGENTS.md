# AGENTS.md

## Defaults
- Use PowerShell 7 for PowerShell commands: `C:\Program Files\PowerShell\7\pwsh.exe`.
- Target chip: `esp32s3`.
- Framework: ESP-IDF C/C++. Do not switch to Arduino unless the user explicitly asks.
- Preferred SDK: EIM-managed ESP-IDF v5.5.2 from `C:\Espressif\tools\eim_idf.json`.
- Fallback SDK: `../references/esp-idf-v5.5.2/`.
- Baseline command from the workspace root: `scripts\build.ps1`.

## Editor Configuration
- For VS Code ESP-IDF extension work, `idf.currentSetup` should be the actual SDK path: `C:\esp\v5.5.2\esp-idf`.
- Do not replace `idf.currentSetup` with the EIM id such as `esp-idf-...`; extension 2.1.0 expects a path here.
- If CMake Tools asks for a kit or compiler, treat it as an editor-side CMake Tools prompt, not an ESP-IDF requirement. ESP-IDF uses its own CMake toolchain and the `xtensa-esp32s3-elf` cross compiler.
- Keep `cmake.configureOnOpen` disabled unless the user explicitly wants CMake Tools to manage this project directly.

## Firmware Direction
- This project is for the ESP32-S3-DevKitC-1 competition work, focused on sensor data plus cloud LLM control.
- Use Wi-Fi plus HTTPS/HTTP or MQTT as the default cloud path.
- Prefer ESP-IDF components, ESP Component Registry packages, and `../references/esp-iot-solution/` drivers before writing low-level sensor drivers by hand.
- Current firmware includes the teammate prototype hardware set in modular form: SHT30, TVOC301, LM393, ST7735, SG90, active beeper, manual button, OV2640 camera, ordinary backend upload, image upload, and pose upload.
- Keep the product loop modular: collect sensor data, evaluate fusion state, optionally upload to ordinary backend, optionally exchange with cloud LLM, parse a command, and apply it to local device state.

## Architecture Rules
- `main/main.c` should remain an orchestrator for config loading, module initialization, and task startup. Do not put device drivers, display drawing internals, HTTP multipart logic, or sensor parsing directly in `main.c`.
- Keep module boundaries:
  - `config/`: Kconfig/sdkconfig loading into `app_config_t`.
  - `sensors/`: SHT30, TVOC301, LM393, and mock samples.
  - `fusion/`: air quality, open-window recommendation, and alarm decisions.
  - `backend/`: ordinary sensor/image/pose HTTP uploads.
  - `cloud/`: LLM endpoint exchange and command parsing.
  - `commands/`: allowed command names and validation.
  - `actuators/`: SG90 and beeper behavior.
  - `inputs/`: manual button handling.
  - `display/`: ST7735 rendering.
  - `camera/`: OV2640 init and frame capture.
  - `state/`: manual override, window, and alarm state.
- Keep ordinary backend upload separate from cloud LLM exchange. Do not merge local server upload URLs into `cloud_client`.
- Keep `APP_*` Kconfig symbol names stable; C code depends on generated `CONFIG_APP_*` macros.
- User-facing Kconfig labels are Chinese under `S3 传感器云端控制`; this is intentional.

## Hardware / Configuration Notes
- Defaults must remain safe: mock sensor enabled and Wi-Fi/backend/cloud/camera/display/actuator/button disabled.
- Full prototype behavior is enabled locally through menuconfig/local `sdkconfig`; never commit local `sdkconfig`.
- The old prototype used GPIO10 for both OV2640 XCLK and TFT CS. The modular default keeps camera XCLK on GPIO10 and sets TFT CS to GPIO5. Verify wiring before enabling camera and display together.
- Camera defaults preserve the verified OV2640 setup: QVGA JPEG, 10 MHz XCLK, one DRAM framebuffer.

## Secrets
- Never hard-code Wi-Fi passwords, API keys, tokens, or model credentials.
- Use local `sdkconfig`, environment variables, or menuconfig-style values for secrets.
- Keep example endpoint/model names non-sensitive.
- Do not hard-code local backend IPs or URLs in source files.
- Do not commit build outputs, `managed_components/`, `dependencies.lock`, local `sdkconfig`, binaries, captured images, or cloned SDK/reference repositories.

## Verification
- Run `scripts\build.ps1` from the workspace root before reporting firmware changes complete.
- If building manually inside this directory, activate ESP-IDF first, then run `idf.py set-target esp32s3` and `idf.py build`.
- Only run `idf.py -p COMx flash monitor` after the user confirms the serial port and that a board is connected.
