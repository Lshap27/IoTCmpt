#include "http_upload.h"

#include <stdlib.h>
#include <string.h>

#include "app_string.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "HTTP_UPLOAD";
static app_config_t s_config;

static bool string_is_empty(const char *value) {
    return !value || value[0] == '\0';
}

esp_err_t http_upload_init(const app_config_t *config) {
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;
    if (!s_config.image_upload_enabled) {
        ESP_LOGW(TAG, "HTTP 图片上传已禁用");
    }

    return ESP_OK;
}

esp_err_t http_upload_jpeg(const char *url, const uint8_t *data, size_t len) {
    if (string_is_empty(url) || !data || len == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (!s_config.image_upload_enabled) {
        return ESP_ERR_INVALID_STATE;
    }

    const char boundary[] = "----ESP32Boundary";
    char header[256] = {0};
    char footer[64] = {0};

    const bool header_ok = app_string_append(header, sizeof(header), "--") &&
                           app_string_append(header, sizeof(header), boundary) &&
                           app_string_append(header, sizeof(header),
                                             "\r\n"
                                             "Content-Disposition: form-data; name=\"file\"; filename=\"image.jpg\"\r\n"
                                             "Content-Type: image/jpeg\r\n"
                                             "\r\n");
    const bool footer_ok = app_string_append(footer, sizeof(footer), "\r\n--") &&
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
