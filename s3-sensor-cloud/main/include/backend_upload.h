#pragma once

#include <stddef.h>
#include <stdint.h>

#include "app_config.h"
#include "commands.h"
#include "esp_err.h"
#include "fusion.h"
#include "sensors.h"

esp_err_t backend_upload_init(const app_config_t *config);
esp_err_t backend_upload_sensor(const sensor_sample_t *sample, const fusion_state_t *state);
esp_err_t backend_upload_jpeg(const char *url, const uint8_t *data, size_t len);
esp_err_t backend_poll_command(cloud_command_t *out_command, int *out_command_id);
esp_err_t backend_ack_command(int command_id);
