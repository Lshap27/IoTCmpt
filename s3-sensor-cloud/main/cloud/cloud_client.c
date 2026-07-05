#include "cloud_client.h"

#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "CLOUD";
static app_config_t s_config;

static bool string_is_empty(const char *value)
{
    return !value || value[0] == '\0';
}

static cJSON *build_payload(const sensor_sample_t *sample, const fusion_state_t *state)
{
    cJSON *root = cJSON_CreateObject();
    cJSON *device_state = cJSON_CreateObject();
    cJSON *allowed_commands = cJSON_CreateArray();

    if (!root || !device_state || !allowed_commands) {
        cJSON_Delete(root);
        cJSON_Delete(device_state);
        cJSON_Delete(allowed_commands);
        return NULL;
    }

    cJSON_AddStringToObject(root, "model", s_config.cloud_model);
    cJSON_AddItemToObject(root, "device_state", device_state);

    cJSON_AddNumberToObject(device_state, "timestamp_ms", (double)sample->timestamp_ms);
    cJSON_AddBoolToObject(device_state, "climate_valid", sample->climate_valid);
    cJSON_AddNumberToObject(device_state, "temperature_c", sample->temperature_c);
    cJSON_AddNumberToObject(device_state, "humidity_percent", sample->humidity_percent);
    cJSON_AddBoolToObject(device_state, "air_valid", sample->air_valid);
    cJSON_AddNumberToObject(device_state, "tvoc_ppb", sample->tvoc_ppb);
    cJSON_AddNumberToObject(device_state, "hcho_ug_m3", sample->hcho_ug_m3);
    cJSON_AddNumberToObject(device_state, "eco2_ppm", sample->eco2_ppm);
    cJSON_AddBoolToObject(device_state, "light_valid", sample->light_valid);
    cJSON_AddBoolToObject(device_state, "light_is_dark", sample->light_is_dark);

    cJSON_AddStringToObject(device_state, "air_quality", fusion_air_quality_name(state->air_quality));
    cJSON_AddBoolToObject(device_state, "recommend_open_window", state->recommend_open_window);
    cJSON_AddBoolToObject(device_state, "alarm_enabled", state->alarm_enabled);
    cJSON_AddStringToObject(device_state, "reason", state->reason);

    cJSON_AddItemToArray(allowed_commands, cJSON_CreateString("window.open"));
    cJSON_AddItemToArray(allowed_commands, cJSON_CreateString("window.close"));
    cJSON_AddItemToArray(allowed_commands, cJSON_CreateString("alarm.on"));
    cJSON_AddItemToArray(allowed_commands, cJSON_CreateString("alarm.off"));
    cJSON_AddItemToObject(root, "allowed_commands", allowed_commands);

    return root;
}

static esp_err_t command_from_json_object(const cJSON *object, cloud_command_t *out_command)
{
    const cJSON *command = cJSON_GetObjectItemCaseSensitive(object, "command");
    if (!cJSON_IsString(command) || !command->valuestring) {
        return ESP_ERR_NOT_FOUND;
    }

    esp_err_t err = command_from_name(command->valuestring, out_command);
    if (err != ESP_OK) {
        return err;
    }

    const cJSON *confidence = cJSON_GetObjectItemCaseSensitive(object, "confidence");
    if (cJSON_IsNumber(confidence)) {
        out_command->confidence = (float)confidence->valuedouble;
    }

    const cJSON *parameter = cJSON_GetObjectItemCaseSensitive(object, "parameter");
    if (cJSON_IsString(parameter) && parameter->valuestring) {
        (void)snprintf(out_command->parameter, sizeof(out_command->parameter), "%s", parameter->valuestring);
    }

    const char *printed = cJSON_PrintUnformatted((cJSON *)object);
    if (printed) {
        (void)snprintf(out_command->raw, sizeof(out_command->raw), "%s", printed);
        cJSON_free((void *)printed);
    }

    return ESP_OK;
}

static esp_err_t parse_command_response(const char *response, cloud_command_t *out_command)
{
    if (!response || !out_command) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);

    cJSON *root = cJSON_Parse(response);
    if (!root) {
        ESP_LOGW(TAG, "Cloud response is not valid JSON");
        return ESP_ERR_INVALID_RESPONSE;
    }

    esp_err_t err = command_from_json_object(root, out_command);
    if (err == ESP_ERR_NOT_FOUND) {
        const cJSON *choices = cJSON_GetObjectItemCaseSensitive(root, "choices");
        const cJSON *first_choice = cJSON_IsArray(choices) ? cJSON_GetArrayItem(choices, 0) : NULL;
        const cJSON *message = first_choice ? cJSON_GetObjectItemCaseSensitive(first_choice, "message") : NULL;
        const cJSON *content = message ? cJSON_GetObjectItemCaseSensitive(message, "content") : NULL;

        if (cJSON_IsString(content) && content->valuestring) {
            cJSON *content_json = cJSON_Parse(content->valuestring);
            if (content_json) {
                err = command_from_json_object(content_json, out_command);
                cJSON_Delete(content_json);
            }
        }
    }

    cJSON_Delete(root);

    if (err == ESP_ERR_NOT_FOUND) {
        ESP_LOGW(TAG, "Cloud response did not include a command");
        command_clear(out_command);
        return ESP_OK;
    }

    return err;
}

esp_err_t cloud_client_init(const app_config_t *config)
{
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;

    if (!s_config.cloud_enabled) {
        ESP_LOGW(TAG, "Cloud client is disabled by configuration");
        return ESP_OK;
    }

    if (string_is_empty(s_config.cloud_endpoint)) {
        ESP_LOGW(TAG, "Cloud client is enabled but endpoint is empty");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Cloud client configured for model '%s'", s_config.cloud_model);
    return ESP_OK;
}

esp_err_t cloud_send_state(
    const sensor_sample_t *sample,
    const fusion_state_t *state,
    cloud_command_t *out_command
)
{
    if (!sample || !state || !out_command) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);

    if (!s_config.cloud_enabled || string_is_empty(s_config.cloud_endpoint)) {
        return ESP_ERR_INVALID_STATE;
    }

    cJSON *payload = build_payload(sample, state);
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }

    char *json = cJSON_PrintUnformatted(payload);
    cJSON_Delete(payload);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }

    esp_http_client_config_t http_config = {
        .url = s_config.cloud_endpoint,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
        .buffer_size = 2048,
        .buffer_size_tx = 2048,
    };

    esp_http_client_handle_t client = esp_http_client_init(&http_config);
    if (!client) {
        cJSON_free(json);
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    if (!string_is_empty(s_config.cloud_token)) {
        char auth_header[APP_CONFIG_CLOUD_TOKEN_MAX_LEN + 16];
        (void)snprintf(auth_header, sizeof(auth_header), "Bearer %s", s_config.cloud_token);
        esp_http_client_set_header(client, "Authorization", auth_header);
    }
    esp_http_client_set_post_field(client, json, strlen(json));

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status_code = esp_http_client_get_status_code(client);
        if (status_code < 200 || status_code >= 300) {
            ESP_LOGW(TAG, "Cloud HTTP status=%d", status_code);
            err = ESP_FAIL;
        } else {
            char response[1024];
            const int len = esp_http_client_read_response(client, response, sizeof(response) - 1);
            if (len > 0) {
                response[len] = '\0';
                err = parse_command_response(response, out_command);
            } else {
                command_clear(out_command);
                err = ESP_OK;
            }
        }
    } else {
        ESP_LOGW(TAG, "Cloud request failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    cJSON_free(json);
    return err;
}
