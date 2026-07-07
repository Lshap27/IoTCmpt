#include "mqtt_app.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "esp_log.h"
#include "mqtt_client.h"

static const char *TAG = "MQTT_APP";

static app_config_t s_config;
static esp_mqtt_client_handle_t s_client;
static mqtt_app_command_handler_t s_command_handler;
static int s_sequence;

static esp_err_t make_topic(char *buffer, size_t buffer_size, const char *suffix)
{
    if (!buffer || buffer_size == 0 || !suffix || s_config.device_id[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }

    const int written = snprintf(buffer, buffer_size, "devices/%s/%s", s_config.device_id, suffix);
    if (written < 0 || written >= (int)buffer_size) {
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}

static void copy_json_string_value(char *dest, size_t dest_size, const char *payload, const char *key)
{
    if (!dest || dest_size == 0) {
        return;
    }
    dest[0] = '\0';
    if (!payload || !key) {
        return;
    }

    char pattern[32];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *match = strstr(payload, pattern);
    if (!match) {
        return;
    }
    match = strchr(match + strlen(pattern), ':');
    if (!match) {
        return;
    }
    match++;
    while (*match == ' ' || *match == '"') {
        match++;
    }
    const char *end = match;
    while (*end && *end != '"' && *end != ',' && *end != '}') {
        end++;
    }
    const size_t len = (size_t)(end - match);
    const size_t copy_len = len < dest_size - 1 ? len : dest_size - 1;
    memcpy(dest, match, copy_len);
    dest[copy_len] = '\0';
}

static void handle_command_payload(const char *payload)
{
    static char command_id[64];
    static char command_type[64];

    copy_json_string_value(command_id, sizeof(command_id), payload, "command_id");
    copy_json_string_value(command_type, sizeof(command_type), payload, "type");

    ESP_LOGI(TAG, "received command id=%s type=%s", command_id, command_type);
    mqtt_app_command_t command = {
        .command_id = command_id,
        .type = command_type,
    };
    if (s_command_handler) {
        s_command_handler(&command);
    }
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void)handler_args;
    (void)base;

    esp_mqtt_event_handle_t event = event_data;
    if (!event) {
        return;
    }

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED: {
        ESP_LOGI(TAG, "connected");
        mqtt_app_publish_status("online");

        char topic[96];
        if (make_topic(topic, sizeof(topic), "command") == ESP_OK) {
            esp_mqtt_client_subscribe(s_client, topic, 1);
            ESP_LOGI(TAG, "subscribed %s", topic);
        }
        break;
    }
    case MQTT_EVENT_DATA: {
        char payload[256] = {0};
        const int copy_len = event->data_len < (int)sizeof(payload) - 1 ? event->data_len : (int)sizeof(payload) - 1;
        memcpy(payload, event->data, copy_len);
        payload[copy_len] = '\0';
        handle_command_payload(payload);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}

esp_err_t mqtt_app_init(const app_config_t *config)
{
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;
    if (!s_config.mqtt_enabled) {
        ESP_LOGW(TAG, "MQTT disabled");
        return ESP_OK;
    }
    if (s_config.mqtt_broker_uri[0] == '\0') {
        ESP_LOGW(TAG, "MQTT broker URI is empty");
        return ESP_ERR_INVALID_STATE;
    }

    esp_mqtt_client_config_t mqtt_config = {
        .broker.address.uri = s_config.mqtt_broker_uri,
    };
    s_client = esp_mqtt_client_init(&mqtt_config);
    if (!s_client) {
        return ESP_FAIL;
    }

    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    return ESP_OK;
}

esp_err_t mqtt_app_start(void)
{
    if (!s_config.mqtt_enabled) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!s_client) {
        return ESP_ERR_INVALID_STATE;
    }
    return esp_mqtt_client_start(s_client);
}

esp_err_t mqtt_app_publish_status(const char *status)
{
    if (!s_client || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    char payload[128];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "status"), TAG, "status topic");
    snprintf(payload, sizeof(payload), "{\"status\":\"%s\"}", status);
    esp_mqtt_client_publish(s_client, topic, payload, 0, 1, true);
    return ESP_OK;
}

esp_err_t mqtt_app_publish_telemetry(void)
{
    if (!s_client) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    char payload[512];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "telemetry"), TAG, "telemetry topic");

    const int temp = 24 + (s_sequence % 4);
    const int humidity = 58 + (s_sequence % 8);
    const int tvoc = 120 + (s_sequence * 7) % 80;
    const bool watch = tvoc > 170;
    snprintf(
        payload,
        sizeof(payload),
        "{\"device_id\":\"%s\",\"sensors\":{\"temperature_c\":%d,\"humidity_percent\":%d,"
        "\"tvoc_ppb\":%d,\"hcho_ug_m3\":30,\"eco2_ppm\":450,\"light_is_dark\":false},"
        "\"state\":{\"window_open\":false,\"alarm_on\":false,\"manual_override\":false},"
        "\"fusion\":{\"air_quality\":\"%s\",\"recommend_open_window\":%s,"
        "\"alarm_enabled\":%s,\"reason\":\"mock firmware telemetry\"}}",
        s_config.device_id,
        temp,
        humidity,
        tvoc,
        watch ? "watch" : "good",
        watch ? "true" : "false",
        watch ? "true" : "false"
    );
    s_sequence++;
    esp_mqtt_client_publish(s_client, topic, payload, 0, 0, false);
    return ESP_OK;
}

esp_err_t mqtt_app_publish_command_ack(const mqtt_app_command_t *command, const char *status, const char *message)
{
    if (!s_client || !command || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    char payload[256];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "command_ack"), TAG, "ack topic");
    snprintf(
        payload,
        sizeof(payload),
        "{\"device_id\":\"%s\",\"command_id\":\"%s\",\"status\":\"%s\",\"message\":\"%s\"}",
        s_config.device_id,
        command->command_id ? command->command_id : "",
        status,
        message ? message : ""
    );
    esp_mqtt_client_publish(s_client, topic, payload, 0, 1, false);
    return ESP_OK;
}

esp_err_t mqtt_app_set_command_handler(mqtt_app_command_handler_t handler)
{
    s_command_handler = handler;
    return ESP_OK;
}
