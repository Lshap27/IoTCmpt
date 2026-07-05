#pragma once

#include "app_config.h"
#include "commands.h"
#include "esp_err.h"
#include "fusion.h"
#include "sensors.h"

esp_err_t cloud_client_init(const app_config_t *config);
esp_err_t cloud_send_state(
    const sensor_sample_t *sample,
    const fusion_state_t *state,
    cloud_command_t *out_command
);
