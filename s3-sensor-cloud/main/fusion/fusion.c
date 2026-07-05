#include "fusion.h"

#include <stdio.h>
#include <string.h>

esp_err_t fusion_evaluate(const sensor_sample_t *sample, fusion_state_t *out_state)
{
    if (!sample || !out_state) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_state, 0, sizeof(*out_state));
    out_state->air_quality = FUSION_AIR_QUALITY_UNKNOWN;

    if (!sample->air_valid && !sample->climate_valid) {
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "no valid sensor data");
        return ESP_OK;
    }

    bool alert = false;
    bool watch = false;

    if (sample->air_valid) {
        alert = sample->eco2_ppm >= 1200 || sample->tvoc_ppb >= 600 || sample->hcho_ug_m3 >= 80;
        watch = sample->eco2_ppm >= 900 || sample->tvoc_ppb >= 350 || sample->hcho_ug_m3 >= 50;
    }

    if (sample->climate_valid) {
        watch = watch || sample->humidity_percent >= 70.0f || sample->temperature_c >= 30.0f;
    }

    if (alert) {
        out_state->air_quality = FUSION_AIR_QUALITY_ALERT;
        out_state->recommend_open_window = true;
        out_state->alarm_enabled = true;
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "air quality alert threshold exceeded");
    } else if (watch) {
        out_state->air_quality = FUSION_AIR_QUALITY_WATCH;
        out_state->recommend_open_window = true;
        out_state->alarm_enabled = false;
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "air quality watch threshold exceeded");
    } else {
        out_state->air_quality = FUSION_AIR_QUALITY_GOOD;
        out_state->recommend_open_window = false;
        out_state->alarm_enabled = false;
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "environment is within normal range");
    }

    return ESP_OK;
}

const char *fusion_air_quality_name(fusion_air_quality_t quality)
{
    switch (quality) {
    case FUSION_AIR_QUALITY_GOOD:
        return "good";
    case FUSION_AIR_QUALITY_WATCH:
        return "watch";
    case FUSION_AIR_QUALITY_ALERT:
        return "alert";
    case FUSION_AIR_QUALITY_UNKNOWN:
    default:
        return "unknown";
    }
}
