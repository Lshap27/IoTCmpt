# AGENTS.md

## Defaults
- Use PowerShell 7 for PowerShell commands: `C:\Program Files\PowerShell\7\pwsh.exe`.
- Target chip: `esp32s3`.
- Framework: ESP-IDF C/C++. Do not switch to Arduino unless the user explicitly asks.
- Preferred SDK: `../references/esp-idf-v5.5.2/`.
- Baseline commands: `idf.py set-target esp32s3`, then `idf.py build`.

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
- Run `idf.py set-target esp32s3` after changing target-sensitive config.
- Run `idf.py build` before reporting firmware changes complete.
- Only run `idf.py -p COMx flash monitor` after the user confirms the serial port and that a board is connected.
