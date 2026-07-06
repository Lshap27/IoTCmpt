# ESP32-S3 Firmware Migration Checklist

Use this checklist before moving code from `s3-sensor-cloud/` into the new
firmware mainline.

## Keep From Legacy Firmware

- `main/sensors`: SHT30, TVOC301, LM393, and mock sampling.
- `main/fusion`: air quality, window recommendation, and alarm state.
- `main/camera`: OV2640 QVGA JPEG capture.
- `main/display`: ST7735 status rendering.
- `main/actuators`: SG90 window servo and active beeper.
- `main/inputs`: manual button.
- `main/state`: local manual override, window, and alarm state.
- Existing Kconfig defaults that keep fresh builds safe.

## Replace Or Rework

- Replace periodic sensor HTTP upload with MQTT telemetry publish.
- Replace backend command polling with MQTT command subscription.
- Keep HTTP only for JPEG upload and diagnostics.
- Keep direct cloud LLM exchange only as an optional debug path, not production
  control flow.

## Target `mqtt_app` Interface

```c
esp_err_t mqtt_app_init(const app_config_t *config);
esp_err_t mqtt_app_start(void);
esp_err_t mqtt_app_publish_status(const char *status);
esp_err_t mqtt_app_publish_telemetry(const sensor_sample_t *sample, const fusion_state_t *fusion);
esp_err_t mqtt_app_publish_command_ack(const cloud_command_t *command, const char *status, const char *message);
esp_err_t mqtt_app_set_command_handler(void (*handler)(const cloud_command_t *command));
```

## Bring-Up Order

1. Build legacy firmware unchanged.
2. Create the new ESP-IDF project shell under `firmware/esp32s3/`.
3. Migrate config and safe defaults.
4. Add MQTT connection and retained `online/offline` status.
5. Publish mock telemetry to the new server stack.
6. Subscribe to commands and log parsed command names.
7. Wire command execution into actuator state.
8. Add JPEG upload after MQTT telemetry is stable.
