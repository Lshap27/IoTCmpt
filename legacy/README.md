# Legacy Compatibility Area

The legacy implementation is not physically moved here yet.

Current legacy paths:

- `backend/`: original FastAPI backend with ESP32 upload endpoints.
- `s3-sensor-cloud/`: verified ESP-IDF firmware with hardware modules.

They remain in their original locations so existing build scripts, ESP-IDF
settings, and hardware fallback workflows keep working during migration.

After `server/`, `web/`, and `firmware/esp32s3/` pass integration and hardware
checks, the old paths can be archived or moved here in a dedicated cleanup
change.

