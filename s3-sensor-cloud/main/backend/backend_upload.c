#include "backend_upload.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "BACKEND";
static app_config_t s_config;

static bool string_is_empty(const char *value)
{
    return !value || value[0] == '\0';
}

esp_err_t backend_upload_init(const app_config_t *config)
{
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;
    if (!s_config.backend_enabled) {
        ESP_LOGW(TAG, "Backend upload disabled");
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
        ESP_LOGW(TAG, "Skip sensor upload: no valid sample fields");
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
            ESP_LOGW(TAG, "Sensor upload HTTP status=%d", status);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "Sensor upload failed: %s", esp_err_to_name(err));
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

    const char *boundary = "----ESP32Boundary";
    char header[256];
    const int header_len = snprintf(
        header,
        sizeof(header),
        "--%s\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"image.jpg\"\r\n"
        "Content-Type: image/jpeg\r\n"
        "\r\n",
        boundary
    );

    char footer[64];
    const int footer_len = snprintf(footer, sizeof(footer), "\r\n--%s--\r\n", boundary);
    if (header_len <= 0 || footer_len <= 0) {
        return ESP_FAIL;
    }

    const size_t total_len = (size_t)header_len + len + (size_t)footer_len;
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

    char content_type[128];
    snprintf(content_type, sizeof(content_type), "multipart/form-data; boundary=%s", boundary);
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_post_field(client, (const char *)body, total_len);

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        if (status < 200 || status >= 300) {
            ESP_LOGW(TAG, "JPEG upload HTTP status=%d", status);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "JPEG upload failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    free(body);
    return err;
}
