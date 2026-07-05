#pragma once

#include <stddef.h>
#include <stdint.h>

#include "app_config.h"
#include "esp_err.h"
#include "fusion.h"
#include "sensors.h"

esp_err_t backend_upload_init(const app_config_t *config);
esp_err_t backend_upload_sensor(const sensor_sample_t *sample, const fusion_state_t *state);
esp_err_t backend_upload_jpeg(const char *url, const uint8_t *data, size_t len);
