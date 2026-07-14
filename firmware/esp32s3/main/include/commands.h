#pragma once

#include <stdbool.h>

#include "esp_err.h"

#define CLOUD_COMMAND_RAW_MAX_LEN   512
#define CLOUD_COMMAND_PARAM_MAX_LEN 384

typedef enum {
    CLOUD_COMMAND_SOURCE_FRONTEND = 0,
    CLOUD_COMMAND_SOURCE_AI,
    CLOUD_COMMAND_SOURCE_EXTERNAL_MCP,
    CLOUD_COMMAND_SOURCE_RULE,
    CLOUD_COMMAND_SOURCE_UNKNOWN,
} cloud_command_source_t;

typedef enum {
    CLOUD_COMMAND_UNSET = 0,
    CLOUD_COMMAND_WINDOW_OPEN,
    CLOUD_COMMAND_WINDOW_CLOSE,
    CLOUD_COMMAND_ALARM_ON,
    CLOUD_COMMAND_ALARM_OFF,
    CLOUD_COMMAND_LED_ON,
    CLOUD_COMMAND_LED_OFF,
    CLOUD_COMMAND_CONTROL_SET_PRIORITY,
    CLOUD_COMMAND_CONTROL_RESUME_AUTO,
    CLOUD_COMMAND_ALARM_SILENCE,
    CLOUD_COMMAND_VOICE_SPEAK,
    CLOUD_COMMAND_DISPLAY_MESSAGE,
    CLOUD_COMMAND_UNKNOWN,
} cloud_command_type_t;

typedef struct {
    cloud_command_type_t type;
    cloud_command_source_t source;
    char parameter[CLOUD_COMMAND_PARAM_MAX_LEN];
    float confidence;
    char raw[CLOUD_COMMAND_RAW_MAX_LEN];
} cloud_command_t;

void command_clear(cloud_command_t *command);
esp_err_t command_from_name(const char *name, cloud_command_t *out_command);
esp_err_t command_apply(const cloud_command_t *command);
const char *command_type_name(cloud_command_type_t type);
