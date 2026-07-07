#include "app_config.h"

#include <string.h>

#include "sdkconfig.h"

static void copy_string(char *dest, size_t dest_size, const char *src)
{
    if (!dest || dest_size == 0) {
        return;
    }
    if (!src) {
        dest[0] = '\0';
        return;
    }
    strlcpy(dest, src, dest_size);
}

void app_config_load(app_config_t *config)
{
    if (!config) {
        return;
    }

    memset(config, 0, sizeof(*config));
    copy_string(config->device_id, sizeof(config->device_id), CONFIG_APP_DEVICE_ID);
    config->sensor_interval_ms = CONFIG_APP_SENSOR_INTERVAL_MS;
#ifdef CONFIG_APP_WIFI_ENABLED
    config->wifi_enabled = true;
#else
    config->wifi_enabled = false;
#endif
    copy_string(config->wifi_ssid, sizeof(config->wifi_ssid), CONFIG_APP_WIFI_SSID);
    copy_string(config->wifi_password, sizeof(config->wifi_password), CONFIG_APP_WIFI_PASSWORD);
#ifdef CONFIG_APP_MQTT_ENABLED
    config->mqtt_enabled = true;
#else
    config->mqtt_enabled = false;
#endif
    copy_string(config->mqtt_broker_uri, sizeof(config->mqtt_broker_uri), CONFIG_APP_MQTT_BROKER_URI);
}
