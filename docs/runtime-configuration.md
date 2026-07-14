# Runtime configuration

`config/runtime-config.json` is the versioned catalog for local runtime fields. It records each field owner, default value, secret status and which service must restart. `tools/runtime_config.py` is the single writer for root `.env`, `server/.env` and `web/.env.local`; `tools/configure-local.ps1` is a PowerShell 7 wrapper around that module.

The local panel listens only on `127.0.0.1`, rejects non-local Host/Origin values and requires a random per-process Panel Token for every write. Secrets are shown only as “已配置”. Saving is a two-step operation: preview the diff, confirm it, then explicitly restart only the affected services.

Per-device automation policy is not a startup setting. Configure patrol, vision scheduling and sedentary triggers through `GET/PUT /api/v1/devices/{device_id}/automation-policy` or the main console.

Important process ownership:

- Gateway: database/MQTT/MCP server/external MCP policy, ACK timeout.
- Worker: LLM endpoint/key/model/60-second default timeout, tool limits, leases and patrol scheduler.
- Web: `NEXT_PUBLIC_API_BASE_URL` (build-time setting).
- Firmware simulator: scenario, 1-60 second telemetry interval, periodic image switch and 10-3600 second image interval. These fields restart only `simulator`.
- Firmware: Wi-Fi, MQTT broker, device ID and `/api/v1/.../images` upload URL in `sdkconfig`.

The panel's real-board defaults are intentionally conservative: physical modules, networking, image upload and mock sensors stay off until the operator selects and verifies a board configuration. A full-feature compile profile is labeled “compile check” and cannot be applied as a ready-to-flash image. The panel reports duplicate GPIO, USB GPIO19/20 and octal-PSRAM GPIO35-37 conflicts; unknown wiring remains “待核对” rather than silently accepted.

`AIOT_MCP_INTERNAL_TOKEN` is shared only by Gateway and Worker. Generate it through the configuration tool, never expose it to the browser, and never reuse the external read/control tokens.

All Windows wrappers invoke PowerShell 7 and delegate environment-file writes to `tools/runtime_config.py`. The panel must not maintain a second `.env` serialization path.
