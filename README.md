# IoTCmpt Workspace

ESP32-S3 competition workspace for a sensor + cloud LLM control firmware.

## Layout

- `s3-sensor-cloud/`: the ESP-IDF product firmware project.
- `scripts/`: workspace-level setup and build helpers.
- `references/RESOURCE_INDEX.md`: notes for optional local SDKs, docs, and reference repositories.

Large SDK and reference repositories are intentionally not tracked in Git. If they
are needed on a local machine, keep them under `references/` and leave them
ignored.

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
