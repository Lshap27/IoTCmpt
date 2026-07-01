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
- Keep the first product loop simple: collect sensor data, build JSON, send it to a cloud model endpoint, parse a command, and apply it to local device state.

## Secrets
- Never hard-code Wi-Fi passwords, API keys, tokens, or model credentials.
- Use `sdkconfig.defaults.example`, local `sdkconfig`, environment variables, or menuconfig-style values for secrets.
- Keep example endpoint/model names non-sensitive.

## Verification
- Run `scripts\build.ps1` from the workspace root before reporting firmware changes complete.
- If building manually inside this directory, activate ESP-IDF first, then run `idf.py set-target esp32s3` and `idf.py build`.
- Only run `idf.py -p COMx flash monitor` after the user confirms the serial port and that a board is connected.
