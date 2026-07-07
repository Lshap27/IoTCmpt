#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    int64_t timestamp_ms;

    float temperature_c;
    float humidity_percent;
    bool climate_valid;

    uint16_t tvoc_ppb;
    uint16_t hcho_ug_m3;
    uint16_t eco2_ppm;
    bool air_valid;

    bool light_is_dark;
    bool light_valid;
} sensor_sample_t;

esp_err_t sensors_init(void);
esp_err_t sensors_read(sensor_sample_t *out_sample);
