#include "fusion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static void append_reason(char *dest, size_t dest_size, const char *format, ...)
{
    if (!dest || dest_size == 0) {
        return;
    }

    const size_t used = strnlen(dest, dest_size);
    if (used >= dest_size - 1) {
        return;
    }

    va_list args;
    va_start(args, format);
    (void)vsnprintf(dest + used, dest_size - used, format, args);
    va_end(args);
}

esp_err_t fusion_evaluate(const sensor_sample_t *sample, fusion_state_t *out_state)
{
    if (!sample || !out_state) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_state, 0, sizeof(*out_state));
    out_state->air_quality = FUSION_AIR_QUALITY_UNKNOWN;

    if (!sample->air_valid && !sample->climate_valid && !sample->light_valid) {
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "no valid sensor data");
        return ESP_OK;
    }

    bool bad = false;
    bool watch = false;

    if (sample->climate_valid) {
        if (sample->temperature_c > 32.0f) {
            bad = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "temperature critical %.1fC; ", sample->temperature_c);
        } else if (sample->temperature_c > 28.0f) {
            watch = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "temperature high %.1fC; ", sample->temperature_c);
        }

        if (sample->humidity_percent > 75.0f || sample->humidity_percent < 30.0f) {
            watch = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "humidity abnormal %.1f%%; ", sample->humidity_percent);
        }
    }

    if (sample->air_valid) {
        if (sample->tvoc_ppb > 600) {
            bad = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "TVOC critical %u; ", sample->tvoc_ppb);
        } else if (sample->tvoc_ppb > 300) {
            watch = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "TVOC high %u; ", sample->tvoc_ppb);
        }

        if (sample->hcho_ug_m3 > 100) {
            bad = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "HCHO critical %u; ", sample->hcho_ug_m3);
        } else if (sample->hcho_ug_m3 > 60) {
            watch = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "HCHO high %u; ", sample->hcho_ug_m3);
        }

        if (sample->eco2_ppm > 1500) {
            bad = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "eCO2 critical %u; ", sample->eco2_ppm);
        } else if (sample->eco2_ppm > 1000) {
            watch = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "eCO2 high %u; ", sample->eco2_ppm);
        }
    }

    if (sample->light_valid && sample->light_is_dark) {
        append_reason(out_state->reason, sizeof(out_state->reason), "light is dim; ");
    }

    if (bad) {
        out_state->air_quality = FUSION_AIR_QUALITY_ALERT;
        out_state->recommend_open_window = true;
        out_state->alarm_enabled = true;
    } else if (watch) {
        out_state->air_quality = FUSION_AIR_QUALITY_WATCH;
        out_state->recommend_open_window = true;
        out_state->alarm_enabled = false;
    } else {
        out_state->air_quality = FUSION_AIR_QUALITY_GOOD;
        out_state->recommend_open_window = false;
        out_state->alarm_enabled = false;
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "air quality good");
    }

    if (out_state->reason[0] == '\0') {
        (void)snprintf(out_state->reason, sizeof(out_state->reason), "%s", fusion_air_quality_name(out_state->air_quality));
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
