#pragma once

#include "app_config.h"
#include "esp_err.h"

typedef struct {
    const char *command_id;
    const char *type;
} mqtt_app_command_t;

typedef void (*mqtt_app_command_handler_t)(const mqtt_app_command_t *command);

esp_err_t mqtt_app_init(const app_config_t *config);
esp_err_t mqtt_app_start(void);
esp_err_t mqtt_app_publish_status(const char *status);
esp_err_t mqtt_app_publish_telemetry(void);
esp_err_t mqtt_app_publish_command_ack(const mqtt_app_command_t *command, const char *status, const char *message);
esp_err_t mqtt_app_set_command_handler(mqtt_app_command_handler_t handler);

