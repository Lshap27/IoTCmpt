#pragma once

#include "app_status.h"
#include "esp_err.h"
#include "fusion.h"
#include "sensors.h"

esp_err_t display_init(void);
esp_err_t display_render(const sensor_sample_t *sample, const fusion_state_t *state, const app_status_t *status);
