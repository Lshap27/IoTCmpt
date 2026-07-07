#pragma once

#include <stdbool.h>
#include <stdint.h>

#define APP_CONFIG_DEVICE_ID_MAX_LEN 64
#define APP_CONFIG_WIFI_SSID_MAX_LEN 32
#define APP_CONFIG_WIFI_PASSWORD_MAX_LEN 64
#define APP_CONFIG_MQTT_URI_MAX_LEN 128

typedef struct {
    char device_id[APP_CONFIG_DEVICE_ID_MAX_LEN];
    uint32_t sensor_interval_ms;
    bool wifi_enabled;
    char wifi_ssid[APP_CONFIG_WIFI_SSID_MAX_LEN];
    char wifi_password[APP_CONFIG_WIFI_PASSWORD_MAX_LEN];
    bool mqtt_enabled;
    char mqtt_broker_uri[APP_CONFIG_MQTT_URI_MAX_LEN];
} app_config_t;

void app_config_load(app_config_t *config);

