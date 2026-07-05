#include "app_config.h"

#include <stdio.h>
#include <string.h>

#include "sdkconfig.h"

static void copy_config_string(char *dest, size_t dest_size, const char *source)
{
    if (dest_size == 0) {
        return;
    }

    if (!source) {
        dest[0] = '\0';
        return;
    }

    (void)snprintf(dest, dest_size, "%s", source);
}

esp_err_t app_config_load(app_config_t *out_config)
{
    if (!out_config) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_config, 0, sizeof(*out_config));

    out_config->wifi_enabled = CONFIG_APP_WIFI_ENABLED;
    copy_config_string(out_config->wifi_ssid, sizeof(out_config->wifi_ssid), CONFIG_APP_WIFI_SSID);
    copy_config_string(out_config->wifi_password, sizeof(out_config->wifi_password), CONFIG_APP_WIFI_PASSWORD);

    out_config->cloud_enabled = CONFIG_APP_CLOUD_ENABLED;
    copy_config_string(out_config->cloud_endpoint, sizeof(out_config->cloud_endpoint), CONFIG_APP_CLOUD_ENDPOINT);
    copy_config_string(out_config->cloud_model, sizeof(out_config->cloud_model), CONFIG_APP_CLOUD_MODEL);
    copy_config_string(out_config->cloud_token, sizeof(out_config->cloud_token), CONFIG_APP_CLOUD_TOKEN);

    out_config->sensor_mock_enabled = CONFIG_APP_SENSOR_MOCK_ENABLED;
    out_config->sensor_interval_ms = CONFIG_APP_SENSOR_INTERVAL_MS;
    if (out_config->sensor_interval_ms == 0) {
        out_config->sensor_interval_ms = 5000;
    }

    return ESP_OK;
}
