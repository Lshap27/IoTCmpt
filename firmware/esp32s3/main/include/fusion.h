#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"
#include "sensors.h"

#define FUSION_REASON_MAX_LEN 128

typedef enum {
    FUSION_AIR_QUALITY_UNKNOWN = 0,
    FUSION_AIR_QUALITY_GOOD,
    FUSION_AIR_QUALITY_WATCH,
    FUSION_AIR_QUALITY_ALERT,
} fusion_air_quality_t;

typedef struct {
    fusion_air_quality_t air_quality;
    bool recommend_open_window;
    bool alarm_enabled;
    char reason[FUSION_REASON_MAX_LEN];
} fusion_state_t;

esp_err_t fusion_evaluate(const sensor_sample_t *sample, fusion_state_t *out_state);
const char *fusion_air_quality_name(fusion_air_quality_t quality);
