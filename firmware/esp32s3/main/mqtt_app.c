#include "mqtt_app.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "control_state.h"
#include "esp_check.h"
#include "esp_log.h"
#include "mqtt_client.h"

static const char *TAG = "MQTT_APP";

static app_config_t s_config;
static esp_mqtt_client_handle_t s_client;
static mqtt_app_command_handler_t s_command_handler;
static char s_status_topic[96];
static char s_status_offline_payload[128];

static esp_err_t make_topic(char *buffer, size_t buffer_size, const char *suffix) {
    if (!buffer || buffer_size == 0 || !suffix || s_config.device_id[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }

    const int written = snprintf(buffer, buffer_size, "devices/%s/%s", s_config.device_id, suffix);
    if (written < 0 || written >= (int)buffer_size) {
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}

static void copy_json_string(char *dest, size_t dest_size, const cJSON *root, const char *key) {
    if (!dest || dest_size == 0) {
        return;
    }
    dest[0] = '\0';
    if (!root || !key) {
        return;
    }

    const cJSON *item = cJSON_GetObjectItemCaseSensitive(root, key);
    if (cJSON_IsString(item) && item->valuestring) {
        strlcpy(dest, item->valuestring, dest_size);
    }
}

static void handle_command_payload(const char *payload) {
    if (!payload) {
        return;
    }

    cJSON *root = cJSON_Parse(payload);
    if (!root) {
        ESP_LOGW(TAG, "command payload is not JSON: %s", payload);
        return;
    }

    mqtt_app_command_t envelope = {0};
    command_clear(&envelope.command);
    copy_json_string(envelope.command_id, sizeof(envelope.command_id), root, "command_id");

    char command_type[64] = {0};
    copy_json_string(command_type, sizeof(command_type), root, "type");
    esp_err_t err = command_from_name(command_type, &envelope.command);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "unsupported command type=%s", command_type);
    }

    const cJSON *confidence = cJSON_GetObjectItemCaseSensitive(root, "confidence");
    if (cJSON_IsNumber(confidence)) {
        envelope.command.confidence = (float)confidence->valuedouble;
    }

    char source[24] = {0};
    copy_json_string(source, sizeof(source), root, "source");
    if (strcmp(source, "llm") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_LLM;
    } else if (strcmp(source, "rule") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_RULE;
    } else {
        envelope.command.source = CLOUD_COMMAND_SOURCE_FRONTEND;
    }

    const cJSON *parameter = cJSON_GetObjectItemCaseSensitive(root, "parameter");
    if (parameter) {
        char *parameter_json = cJSON_PrintUnformatted(parameter);
        if (parameter_json) {
            strlcpy(envelope.command.parameter, parameter_json, sizeof(envelope.command.parameter));
            cJSON_free(parameter_json);
        }
    }

    strlcpy(envelope.command.raw, payload, sizeof(envelope.command.raw));
    ESP_LOGI(TAG, "received command id=%s type=%s", envelope.command_id, command_type);
    if (s_command_handler) {
        s_command_handler(&envelope);
    }

    cJSON_Delete(root);
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
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
        /* 超过客户端缓冲区的消息会拆成多个 DATA 事件，单个分片不是完整 JSON，直接丢弃 */
        if (event->current_data_offset != 0 || event->data_len != event->total_data_len) {
            ESP_LOGW(TAG, "discarding fragmented MQTT message (offset=%d len=%d total=%d)", event->current_data_offset,
                     event->data_len, event->total_data_len);
            break;
        }
        char *payload = malloc((size_t)event->data_len + 1);
        if (!payload) {
            ESP_LOGE(TAG, "no memory for command payload (%d bytes)", event->data_len);
            break;
        }
        memcpy(payload, event->data, event->data_len);
        payload[event->data_len] = '\0';
        handle_command_payload(payload);
        free(payload);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}

esp_err_t mqtt_app_init(const app_config_t *config) {
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

    ESP_RETURN_ON_ERROR(make_topic(s_status_topic, sizeof(s_status_topic), "status"), TAG, "status topic");
    snprintf(s_status_offline_payload, sizeof(s_status_offline_payload), "{\"status\":\"offline\"}");

    esp_mqtt_client_config_t mqtt_config = {
        .broker.address.uri = s_config.mqtt_broker_uri,
        .session.last_will.topic = s_status_topic,
        .session.last_will.msg = s_status_offline_payload,
        .session.last_will.qos = 1,
        .session.last_will.retain = true,
    };
    s_client = esp_mqtt_client_init(&mqtt_config);
    if (!s_client) {
        return ESP_FAIL;
    }

    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    return ESP_OK;
}

esp_err_t mqtt_app_start(void) {
    if (!s_config.mqtt_enabled) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!s_client) {
        return ESP_ERR_INVALID_STATE;
    }
    return esp_mqtt_client_start(s_client);
}

esp_err_t mqtt_app_publish_status(const char *status) {
    if (!s_client || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    char payload[128];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "status"), TAG, "status topic");
    snprintf(payload, sizeof(payload), "{\"status\":\"%s\"}", status);
    const int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, 1, true);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

static void add_optional_number(cJSON *root, const char *name, bool valid, double value) {
    if (valid) {
        cJSON_AddNumberToObject(root, name, value);
    } else {
        cJSON_AddNullToObject(root, name);
    }
}

static char *build_telemetry_json(const sensor_sample_t *sample, const fusion_state_t *fusion) {
    control_state_t control = {0};
    control_state_get(&control);

    cJSON *root = cJSON_CreateObject();
    cJSON *sensors = cJSON_CreateObject();
    cJSON *state = cJSON_CreateObject();
    cJSON *fusion_json = cJSON_CreateObject();
    if (!root || !sensors || !state || !fusion_json) {
        cJSON_Delete(root);
        cJSON_Delete(sensors);
        cJSON_Delete(state);
        cJSON_Delete(fusion_json);
        return NULL;
    }

    cJSON_AddStringToObject(root, "device_id", s_config.device_id);
    add_optional_number(sensors, "temperature_c", sample->climate_valid, sample->temperature_c);
    add_optional_number(sensors, "humidity_percent", sample->climate_valid, sample->humidity_percent);
    add_optional_number(sensors, "tvoc_ppb", sample->air_valid, sample->tvoc_ppb);
    add_optional_number(sensors, "hcho_ug_m3", sample->air_valid, sample->hcho_ug_m3);
    add_optional_number(sensors, "eco2_ppm", sample->air_valid, sample->eco2_ppm);
    if (sample->light_valid) {
        cJSON_AddBoolToObject(sensors, "light_is_dark", sample->light_is_dark);
    } else {
        cJSON_AddNullToObject(sensors, "light_is_dark");
    }
    if (sample->smoke_valid) {
        cJSON_AddBoolToObject(sensors, "smoke_detected", sample->smoke_detected);
    } else {
        cJSON_AddNullToObject(sensors, "smoke_detected");
    }

    cJSON_AddBoolToObject(state, "window_open", control.window_open);
    cJSON_AddBoolToObject(state, "alarm_on", control.alarm_on);
    cJSON_AddBoolToObject(state, "manual_override", control.manual_override);
    cJSON_AddBoolToObject(state, "manual_window_override", control.manual_window_override);
    cJSON_AddBoolToObject(state, "manual_led_override", control.manual_led_override);
    cJSON_AddStringToObject(state, "control_priority", control_priority_name(control.priority));
    cJSON_AddBoolToObject(state, "smoke_silenced", control.smoke_silenced);
    cJSON_AddBoolToObject(state, "led_on", control.led_on);

    cJSON_AddStringToObject(fusion_json, "air_quality", fusion_air_quality_name(fusion->air_quality));
    cJSON_AddBoolToObject(fusion_json, "recommend_open_window", fusion->recommend_open_window);
    cJSON_AddBoolToObject(fusion_json, "alarm_enabled", fusion->alarm_enabled);
    cJSON_AddStringToObject(fusion_json, "reason", fusion->reason);

    cJSON_AddItemToObject(root, "sensors", sensors);
    cJSON_AddItemToObject(root, "state", state);
    cJSON_AddItemToObject(root, "fusion", fusion_json);
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json;
}

esp_err_t mqtt_app_publish_event(const char *type, const char *severity, const char *message) {
    if (!s_client || !type || !severity) {
        return ESP_ERR_INVALID_STATE;
    }
    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "event"), TAG, "event topic");
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(root, "type", type);
    cJSON_AddStringToObject(root, "severity", severity);
    cJSON_AddStringToObject(root, "message", message ? message : "");
    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t err = ESP_OK;
    const int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, 1, false);
    if (msg_id < 0) {
        err = ESP_FAIL;
    }
    cJSON_free(payload);
    return err;
}

esp_err_t mqtt_app_publish_telemetry(const sensor_sample_t *sample, const fusion_state_t *fusion) {
    if (!s_client || !sample || !fusion) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "telemetry"), TAG, "telemetry topic");

    char *payload = build_telemetry_json(sample, fusion);
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }

    const int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, 0, false);
    cJSON_free(payload);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

esp_err_t mqtt_app_publish_command_ack(const mqtt_app_command_t *command, const char *status, const char *message) {
    if (!s_client || !command || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "command_ack"), TAG, "ack topic");

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(root, "device_id", s_config.device_id);
    cJSON_AddStringToObject(root, "command_id", command->command_id);
    cJSON_AddStringToObject(root, "status", status);
    cJSON_AddStringToObject(root, "message", message ? message : "");
    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }

    const int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, 1, false);
    cJSON_free(payload);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

esp_err_t mqtt_app_set_command_handler(mqtt_app_command_handler_t handler) {
    s_command_handler = handler;
    return ESP_OK;
}
