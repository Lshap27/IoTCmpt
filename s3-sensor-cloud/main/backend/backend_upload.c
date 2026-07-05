#include "backend_upload.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "app_string.h"
#include "cJSON.h"
#include "control_state.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "BACKEND";
static app_config_t s_config;

#define BACKEND_COMMAND_RESPONSE_MAX_LEN 512

static bool string_is_empty(const char *value)
{
    return !value || value[0] == '\0';
}

static void strip_trailing_slashes(char *value)
{
    if (!value) {
        return;
    }

    size_t len = strlen(value);
    while (len > 0 && value[len - 1] == '/') {
        value[len - 1] = '\0';
        len--;
    }
}

static bool strip_suffix(char *value, const char *suffix)
{
    if (!value || !suffix) {
        return false;
    }

    const size_t value_len = strlen(value);
    const size_t suffix_len = strlen(suffix);
    if (value_len < suffix_len) {
        return false;
    }
    if (strcmp(value + value_len - suffix_len, suffix) != 0) {
        return false;
    }

    value[value_len - suffix_len] = '\0';
    strip_trailing_slashes(value);
    return true;
}

esp_err_t backend_upload_init(const app_config_t *config)
{
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;
    if (!s_config.backend_enabled) {
        ESP_LOGW(TAG, "普通后端上传已禁用");
        return ESP_OK;
    }

    return ESP_OK;
}

esp_err_t backend_upload_sensor(const sensor_sample_t *sample, const fusion_state_t *state)
{
    if (!sample || !state) {
        return ESP_ERR_INVALID_ARG;
    }

    if (!s_config.backend_enabled || string_is_empty(s_config.sensor_upload_url)) {
        return ESP_ERR_INVALID_STATE;
    }

    if (!sample->climate_valid && !sample->air_valid && !sample->light_valid) {
        ESP_LOGW(TAG, "跳过传感器上传：没有有效采样字段");
        return ESP_ERR_NOT_FOUND;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }

    cJSON_AddNumberToObject(root, "temperature_in", sample->climate_valid ? sample->temperature_c : 25.0);
    cJSON_AddNumberToObject(root, "humidity_in", sample->climate_valid ? sample->humidity_percent : 50.0);
    cJSON_AddNumberToObject(root, "temperature_out", 0);
    cJSON_AddNumberToObject(root, "humidity_out", 0);
    cJSON_AddNumberToObject(root, "co2", sample->air_valid ? sample->eco2_ppm : 0);
    cJSON_AddNumberToObject(root, "tvoc", sample->air_valid ? sample->tvoc_ppb : 0);
    cJSON_AddNumberToObject(root, "hcho", sample->air_valid ? sample->hcho_ug_m3 : 0);
    cJSON_AddNumberToObject(root, "light", sample->light_valid ? (sample->light_is_dark ? 0 : 100) : 50);

    control_state_t control = {0};
    control_state_get(&control);
    cJSON_AddStringToObject(root, "led_status", control.alarm_on ? "on" : "off");
    cJSON_AddStringToObject(root, "window_status", control.window_open ? "open" : "closed");
    cJSON_AddStringToObject(root, "dehumidifier_state", state->recommend_open_window ? "on" : "off");

    cJSON_AddStringToObject(root, "air_quality", fusion_air_quality_name(state->air_quality));
    cJSON_AddBoolToObject(root, "recommend_open_window", state->recommend_open_window);
    cJSON_AddBoolToObject(root, "alarm_enabled", state->alarm_enabled);
    cJSON_AddStringToObject(root, "reason", state->reason);

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }

    esp_http_client_config_t config = {
        .url = s_config.sensor_upload_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
        .buffer_size = 2048,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        cJSON_free(json);
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json, strlen(json));

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        if (status < 200 || status >= 300) {
            ESP_LOGW(TAG, "传感器上传 HTTP 状态码异常：%d", status);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "传感器上传失败：%s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    cJSON_free(json);
    return err;
}

esp_err_t backend_upload_jpeg(const char *url, const uint8_t *data, size_t len)
{
    if (string_is_empty(url) || !data || len == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (!s_config.backend_enabled) {
        return ESP_ERR_INVALID_STATE;
    }

    const char boundary[] = "----ESP32Boundary";
    char header[256] = {0};
    char footer[64] = {0};

    const bool header_ok =
        app_string_append(header, sizeof(header), "--") &&
        app_string_append(header, sizeof(header), boundary) &&
        app_string_append(
            header,
            sizeof(header),
            "\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"image.jpg\"\r\n"
            "Content-Type: image/jpeg\r\n"
            "\r\n"
        );
    const bool footer_ok =
        app_string_append(footer, sizeof(footer), "\r\n--") &&
        app_string_append(footer, sizeof(footer), boundary) &&
        app_string_append(footer, sizeof(footer), "--\r\n");
    if (!header_ok || !footer_ok) {
        return ESP_FAIL;
    }

    const size_t header_len = strlen(header);
    const size_t footer_len = strlen(footer);
    const size_t total_len = header_len + len + footer_len;
    uint8_t *body = malloc(total_len);
    if (!body) {
        return ESP_ERR_NO_MEM;
    }

    memcpy(body, header, header_len);
    memcpy(body + header_len, data, len);
    memcpy(body + header_len + len, footer, footer_len);

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        free(body);
        return ESP_FAIL;
    }

    char content_type[128] = {0};
    if (!app_string_append(content_type, sizeof(content_type), "multipart/form-data; boundary=") ||
        !app_string_append(content_type, sizeof(content_type), boundary)) {
        esp_http_client_cleanup(client);
        free(body);
        return ESP_FAIL;
    }
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_post_field(client, (const char *)body, total_len);

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        if (status < 200 || status >= 300) {
            ESP_LOGW(TAG, "JPEG 上传 HTTP 状态码异常：%d", status);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "JPEG 上传失败：%s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    free(body);
    return err;
}

static esp_err_t build_backend_command_url(char *buffer, size_t buffer_size, const char *suffix)
{
    if (!buffer || buffer_size == 0 || string_is_empty(suffix)) {
        return ESP_ERR_INVALID_ARG;
    }

    buffer[0] = '\0';
    if (string_is_empty(s_config.backend_command_base_url)) {
        return ESP_ERR_INVALID_STATE;
    }

    if (!app_string_append(buffer, buffer_size, s_config.backend_command_base_url)) {
        return ESP_ERR_INVALID_SIZE;
    }

    strip_trailing_slashes(buffer);
    strip_suffix(buffer, "/api/command/pending");
    strip_suffix(buffer, "/api/command");

    if (!app_string_append(buffer, buffer_size, suffix)) {
        return ESP_ERR_INVALID_SIZE;
    }

    return ESP_OK;
}

static esp_err_t parse_backend_command_item(const cJSON *item, cloud_command_t *out_command, int *out_command_id)
{
    if (!item || !out_command || !out_command_id || !cJSON_IsObject(item)) {
        return ESP_ERR_NOT_FOUND;
    }

    const cJSON *status = cJSON_GetObjectItemCaseSensitive(item, "status");
    if (cJSON_IsString(status) && status->valuestring && strcmp(status->valuestring, "success") != 0) {
        return ESP_ERR_NOT_FOUND;
    }

    const cJSON *id = cJSON_GetObjectItemCaseSensitive(item, "id");
    const cJSON *command = cJSON_GetObjectItemCaseSensitive(item, "command");
    if (!cJSON_IsNumber(id) || !cJSON_IsString(command) || !command->valuestring || command->valuestring[0] == '\0') {
        return ESP_ERR_NOT_FOUND;
    }

    esp_err_t err = command_from_name(command->valuestring, out_command);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "后端下发了不支持的命令：%s", command->valuestring);
        return err;
    }

    *out_command_id = id->valueint;
    if (*out_command_id <= 0) {
        command_clear(out_command);
        return ESP_ERR_NOT_FOUND;
    }

    return ESP_OK;
}

static esp_err_t parse_backend_command_response(const char *response, cloud_command_t *out_command, int *out_command_id)
{
    if (string_is_empty(response) || !out_command || !out_command_id) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);
    *out_command_id = 0;

    cJSON *root = cJSON_Parse(response);
    if (!root) {
        ESP_LOGW(TAG, "后端指令响应不是有效 JSON：%s", response);
        return ESP_FAIL;
    }

    esp_err_t err = ESP_ERR_NOT_FOUND;
    if (cJSON_IsArray(root)) {
        const cJSON *item = NULL;
        cJSON_ArrayForEach(item, root) {
            err = parse_backend_command_item(item, out_command, out_command_id);
            if (err == ESP_OK || err == ESP_ERR_NOT_SUPPORTED) {
                break;
            }
        }
    } else if (cJSON_IsObject(root)) {
        err = parse_backend_command_item(root, out_command, out_command_id);
    }

    cJSON_Delete(root);
    if (err == ESP_ERR_NOT_FOUND) {
        command_clear(out_command);
        *out_command_id = 0;
        return ESP_OK;
    }

    return err;
}

esp_err_t backend_poll_command(cloud_command_t *out_command, int *out_command_id)
{
    if (!out_command || !out_command_id) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);
    *out_command_id = 0;

    if (!s_config.backend_enabled || !s_config.backend_command_enabled ||
        string_is_empty(s_config.backend_command_base_url)) {
        return ESP_ERR_INVALID_STATE;
    }

    char url[APP_CONFIG_BACKEND_BASE_URL_MAX_LEN + 32] = {0};
    esp_err_t err = build_backend_command_url(url, sizeof(url), "/api/command/pending");
    if (err != ESP_OK) {
        return err;
    }

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = 5000,
        .buffer_size = 2048,
        .buffer_size_tx = 512,
        .disable_auto_redirect = true,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return ESP_FAIL;
    }

    err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "后端指令 GET 打开失败：%s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return err;
    }

    const int content_len = esp_http_client_fetch_headers(client);
    const int status = esp_http_client_get_status_code(client);
    if (status == 204) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_OK;
    }
    if (status < 200 || status >= 300) {
        ESP_LOGW(TAG, "后端指令 GET HTTP 状态码异常：%d", status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    char response[BACKEND_COMMAND_RESPONSE_MAX_LEN] = {0};
    int len = 0;
    if (content_len > 0 && content_len < (int)sizeof(response)) {
        len = esp_http_client_read(client, response, content_len);
    } else {
        len = esp_http_client_read_response(client, response, sizeof(response) - 1);
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (len <= 0) {
        return ESP_OK;
    }
    if (len >= (int)sizeof(response)) {
        len = sizeof(response) - 1;
    }
    response[len] = '\0';

    err = parse_backend_command_response(response, out_command, out_command_id);
    if (err == ESP_OK && *out_command_id > 0) {
        ESP_LOGI(TAG, "收到普通后端指令 id=%d command=%s", *out_command_id, command_type_name(out_command->type));
    }

    return err;
}

esp_err_t backend_ack_command(int command_id)
{
    if (command_id <= 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (!s_config.backend_enabled || !s_config.backend_command_enabled ||
        string_is_empty(s_config.backend_command_base_url)) {
        return ESP_ERR_INVALID_STATE;
    }

    char suffix[48] = {0};
    snprintf(suffix, sizeof(suffix), "/api/command/ack/%d", command_id);

    char url[APP_CONFIG_BACKEND_BASE_URL_MAX_LEN + sizeof(suffix)] = {0};
    esp_err_t err = build_backend_command_url(url, sizeof(url), suffix);
    if (err != ESP_OK) {
        return err;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(root, "status", "done");
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        cJSON_free(json);
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json, strlen(json));

    err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        if (status < 200 || status >= 300) {
            ESP_LOGW(TAG, "后端指令确认 HTTP 状态码异常：%d", status);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "后端指令确认失败：%s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    cJSON_free(json);
    return err;
}
