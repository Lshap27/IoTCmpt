#include "sensors.h"

#include <string.h>

#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"

static const char *TAG = "SENSORS";
static uint32_t s_mock_counter;

esp_err_t sensors_init(void)
{
    if (CONFIG_APP_SENSOR_MOCK_ENABLED) {
        ESP_LOGW(TAG, "Using mock sensor samples");
        return ESP_OK;
    }

    ESP_LOGW(TAG, "Hardware sensor drivers are not implemented in this rebuild yet");
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t sensors_read(sensor_sample_t *out_sample)
{
    if (!out_sample) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_sample, 0, sizeof(*out_sample));
    out_sample->timestamp_ms = esp_timer_get_time() / 1000;

    if (!CONFIG_APP_SENSOR_MOCK_ENABLED) {
        return ESP_ERR_NOT_SUPPORTED;
    }

    const uint32_t step = s_mock_counter++;
    out_sample->temperature_c = 24.0f + (float)(step % 6) * 0.4f;
    out_sample->humidity_percent = 48.0f + (float)(step % 5) * 1.5f;
    out_sample->climate_valid = true;

    out_sample->tvoc_ppb = 180 + (uint16_t)((step % 8) * 35);
    out_sample->hcho_ug_m3 = 20 + (uint16_t)((step % 4) * 5);
    out_sample->eco2_ppm = 520 + (uint16_t)((step % 7) * 80);
    out_sample->air_valid = true;

    out_sample->light_is_dark = (step % 4) == 0;
    out_sample->light_valid = true;

    return ESP_OK;
}
