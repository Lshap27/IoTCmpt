#pragma once

#include <stdint.h>

#include "esp_err.h"

typedef enum {
    APP_STATUS_LINK_DISABLED = 0,
    APP_STATUS_LINK_READY,
    APP_STATUS_LINK_DEGRADED,
} app_status_link_t;

typedef struct {
    app_status_link_t wifi;
    app_status_link_t cloud;
    esp_err_t last_sensor_result;
    esp_err_t last_cloud_result;
    esp_err_t last_command_result;
    uint32_t loop_count;
} app_status_t;
