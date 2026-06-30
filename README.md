# IoTCmpt Workspace

ESP32-S3 competition workspace for a sensor + cloud LLM control project.

## Layout

- `s3-sensor-cloud/`: actual ESP-IDF firmware project.
- `references/`: competition PDF, resource index, SDK checkouts, documentation, and selected reference repositories.
- `references/esp-idf-v5.5.2/`: fallback/reference ESP-IDF SDK checkout. The preferred local build environment is the EIM-managed ESP-IDF v5.5.2 setup.
- `references/esp-idf-zh_CN-v5.5.2/`: local Chinese ESP-IDF v5.5.2 documentation.
- `references/esp-idf/`: existing ESP-IDF checkout, left untouched even if it tracks `master`.
- `references/esp-iot-solution/`: component and sensor examples used as implementation references.
- `references/esp-adf/`: audio framework kept for possible later voice expansion.

## Build

Use PowerShell 7. The build script first tries the EIM-managed setup recorded in `C:\Espressif\tools\eim_idf.json`, then falls back to `references/esp-idf-v5.5.2/`.

For a fresh clone on another machine, run:

```powershell
.\scripts\setup-esp-idf.ps1
.\scripts\build.ps1
```

The last verified EIM build output was generated under `s3-sensor-cloud/build-eim-after-clean/`.

## Rules

- Put product code in `s3-sensor-cloud/`.
- Put reference material in `references/`.
- Do not commit Wi-Fi passwords, cloud tokens, API keys, or local `sdkconfig`.
- Do not move or mutate the large Espressif SDK/reference repositories unless the user explicitly asks.
