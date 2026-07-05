#include "http_upload.h"

#include <string.h>
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "HTTP_UPLOAD";

esp_err_t http_upload_jpeg(const char *url, const uint8_t *jpeg_data, size_t jpeg_len)
{
    if (url == NULL || jpeg_data == NULL || jpeg_len == 0) {
        ESP_LOGE(TAG, "Invalid upload arguments");
        return ESP_ERR_INVALID_ARG;
    }

    /* ---------- 构建 multipart/form-data ---------- */
    const char *boundary = "----ESP32Boundary";
    const char *field_name = "file";
    const char *filename = "image.jpg";

    /* 计算总长度 */
    char header_part[256];
    int header_len = snprintf(header_part, sizeof(header_part),
        "--%s\r\n"
        "Content-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
        "Content-Type: image/jpeg\r\n"
        "\r\n",
        boundary, field_name, filename);

    char footer_part[64];
    int footer_len = snprintf(footer_part, sizeof(footer_part),
        "\r\n--%s--\r\n", boundary);

    size_t total_len = header_len + jpeg_len + footer_len;

    uint8_t *body = malloc(total_len);
    if (!body) {
        ESP_LOGE(TAG, "malloc failed for multipart body");
        return ESP_ERR_NO_MEM;
    }

    memcpy(body, header_part, header_len);
    memcpy(body + header_len, jpeg_data, jpeg_len);
    memcpy(body + header_len + jpeg_len, footer_part, footer_len);

    /* ---------- HTTP ---------- */
    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        ESP_LOGE(TAG, "Failed to init HTTP client");
        free(body);
        return ESP_FAIL;
    }

    char ct[128];
    snprintf(ct, sizeof(ct), "multipart/form-data; boundary=%s", boundary);
    esp_http_client_set_header(client, "Content-Type", ct);
    esp_http_client_set_post_field(client, (const char *)body, total_len);

    ESP_LOGI(TAG, "Uploading JPEG to %s, size=%d bytes", url, (int)jpeg_len);

    esp_err_t err = esp_http_client_perform(client);

    if (err == ESP_OK) {
        int status_code = esp_http_client_get_status_code(client);
        int content_length = esp_http_client_get_content_length(client);

        ESP_LOGI(TAG, "HTTP POST status=%d, content_length=%d",
                 status_code, content_length);

        if (status_code >= 200 && status_code < 300) {
            ESP_LOGI(TAG, "Upload success");
        } else {
            ESP_LOGE(TAG, "Upload failed, HTTP status=%d", status_code);
            /* print server error detail */
            char buf[256];
            int len = esp_http_client_read_response(client, buf, sizeof(buf) - 1);
            if (len > 0) {
                buf[len] = '\0';
                ESP_LOGE(TAG, "Server response: %s", buf);
            }
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGE(TAG, "HTTP POST failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    free(body);
    return err;
}
