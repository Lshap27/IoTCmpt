#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#define APP_CONFIG_WIFI_SSID_MAX_LEN 32
#define APP_CONFIG_WIFI_PASSWORD_MAX_LEN 64
#define APP_CONFIG_CLOUD_ENDPOINT_MAX_LEN 256
#define APP_CONFIG_CLOUD_MODEL_MAX_LEN 64
#define APP_CONFIG_CLOUD_TOKEN_MAX_LEN 256

typedef struct {
    bool wifi_enabled;
    char wifi_ssid[APP_CONFIG_WIFI_SSID_MAX_LEN + 1];
    char wifi_password[APP_CONFIG_WIFI_PASSWORD_MAX_LEN + 1];

    bool cloud_enabled;
    char cloud_endpoint[APP_CONFIG_CLOUD_ENDPOINT_MAX_LEN + 1];
    char cloud_model[APP_CONFIG_CLOUD_MODEL_MAX_LEN + 1];
    char cloud_token[APP_CONFIG_CLOUD_TOKEN_MAX_LEN + 1];

    bool sensor_mock_enabled;
    uint32_t sensor_interval_ms;
} app_config_t;

esp_err_t app_config_load(app_config_t *out_config);
