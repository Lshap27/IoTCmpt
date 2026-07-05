# IoTCmpt Workspace

ESP32-S3 competition workspace for a sensor + backend upload + cloud LLM
control firmware.

## Layout

- `s3-sensor-cloud/`: the ESP-IDF product firmware project.
- `backend/`: FastAPI backend for sensor upload, image storage, pose detection,
  dashboard APIs, command queue, and cloud LLM exchange.
- `scripts/`: workspace-level setup and build helpers.
- `references/RESOURCE_INDEX.md`: notes for optional local SDKs, docs, and reference repositories.

Large SDK and reference repositories are intentionally not tracked in Git. If they
are needed on a local machine, keep them under `references/` and leave them
ignored.

## Current Firmware State

The product firmware is modularized under `s3-sensor-cloud/main/` and currently
contains the teammate prototype features behind menuconfig switches:

- SHT30, TVOC301, and LM393 sensor sampling.
- Local fusion rules for air quality, window recommendation, and alarm state.
- Ordinary backend uploads for sensor JSON, camera images, and pose detection.
- Optional cloud LLM exchange and downstream command parsing.
- SG90 servo, active beeper, manual button, ST7735 display, and OV2640 camera modules.

The default configuration is safe for a fresh checkout: mock sensor data is on,
and Wi-Fi, backend upload, cloud, camera, display, actuator, and button modules
are off. Enable real hardware and endpoints from local `sdkconfig`/menuconfig.

## Backend

The backend lives in `backend/` and is versioned with the firmware protocol. It
keeps the current ESP32 upload endpoints stable:

- `POST /api/upload_sensor`
- `POST /api/upload_image`
- `POST /api/detect_pose`
- `POST /api/cloud/exchange`

See `backend/README.md` for environment variables, database migration, Docker
Compose, and menuconfig URL examples.

## Build

Use PowerShell 7 on Windows:

```powershell
.\scripts\build.ps1
```

The build script prefers an EIM-managed ESP-IDF v5.5.2 setup from
`C:\Espressif\tools\eim_idf.json`, then falls back to
`references\esp-idf-v5.5.2\` if present.

For a fresh machine without EIM:

```powershell
.\scripts\setup-esp-idf.ps1
.\scripts\build.ps1
```

## Rules

- Keep product firmware in `s3-sensor-cloud/`.
- Keep optional local SDKs, docs, and third-party examples in `references/`.
- Do not commit Wi-Fi passwords, API tokens, model credentials, or local `sdkconfig`.
- Configure secrets through local ESP-IDF menuconfig/sdkconfig values, not source files.
- Do not commit ESP-IDF build outputs, `managed_components/`, `dependencies.lock`, or cloned SDKs.
