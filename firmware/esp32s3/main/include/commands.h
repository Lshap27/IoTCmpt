#pragma once

#include <stdbool.h>

#include "esp_err.h"

#define CLOUD_COMMAND_RAW_MAX_LEN   192
#define CLOUD_COMMAND_PARAM_MAX_LEN 64

typedef enum {
    CLOUD_COMMAND_NONE = 0,
    CLOUD_COMMAND_WINDOW_OPEN,
    CLOUD_COMMAND_WINDOW_CLOSE,
    CLOUD_COMMAND_ALARM_ON,
    CLOUD_COMMAND_ALARM_OFF,
    CLOUD_COMMAND_UNKNOWN,
} cloud_command_type_t;

typedef struct {
    cloud_command_type_t type;
    char parameter[CLOUD_COMMAND_PARAM_MAX_LEN];
    float confidence;
    char raw[CLOUD_COMMAND_RAW_MAX_LEN];
} cloud_command_t;

void command_clear(cloud_command_t *command);
esp_err_t command_from_name(const char *name, cloud_command_t *out_command);
esp_err_t command_apply(const cloud_command_t *command);
const char *command_type_name(cloud_command_type_t type);
