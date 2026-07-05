#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "cJSON.h"
#include "sensor_upload.h"

static const char *TAG = "SENSOR_UPLOAD";

// ========== 后端地址 ==========
#define SENSOR_SERVER_URL "http://example.invalid/api/upload_sensor"

// ========== 上传传感器数据 ==========
esp_err_t upload_sensor_data(const sensor_data_t *data)
{
    if (!data) {
        ESP_LOGE(TAG, "数据指针为空");
        return ESP_ERR_INVALID_ARG;
    }

    // 检查是否有有效数据
    if (!data->sht30_valid && !data->tvoc_valid) {
        ESP_LOGW(TAG, "没有有效的传感器数据，跳过上传");
        return ESP_FAIL;
    }

    // 1. 创建JSON对象
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        ESP_LOGE(TAG, "创建JSON对象失败");
        return ESP_ERR_NO_MEM;
    }

    // 2. 添加数据（映射到后端格式）
    // temperature_in: SHT30温度，无效时默认25.0
    cJSON_AddNumberToObject(root, "temperature_in",
                           data->sht30_valid ? data->temperature : 25.0);

    // humidity_in: SHT30湿度，无效时默认50.0
    cJSON_AddNumberToObject(root, "humidity_in",
                           data->sht30_valid ? data->humidity : 50.0);

    // temperature_out: 没有室外温度传感器，固定为0
    cJSON_AddNumberToObject(root, "temperature_out", 0);

    // humidity_out: 没有室外湿度传感器，固定为0
    cJSON_AddNumberToObject(root, "humidity_out", 0);

    // co2: TVOC301的ECO2值，无效时默认0
    cJSON_AddNumberToObject(root, "co2",
                           data->tvoc_valid ? data->eco2 : 0);

    // tvoc: TVOC301的TVOC值，无效时默认0
    cJSON_AddNumberToObject(root, "tvoc",
                           data->tvoc_valid ? data->tvoc : 0);

    // hcho: TVOC301的HCHO值，无效时默认0
    cJSON_AddNumberToObject(root, "hcho",
                           data->tvoc_valid ? data->hcho : 0);

    // light: 光照映射 (0=暗, 1=亮) → 亮=100, 暗=0
    int light_value = 50;
    if (data->light_valid) {
        light_value = data->light_dark ? 0 : 100;
    }
    cJSON_AddNumberToObject(root, "light", light_value);

    // 3. 转换为JSON字符串
    char *json_string = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (!json_string) {
        ESP_LOGE(TAG, "JSON序列化失败");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "📤 上报: T_in=%.1f°C H_in=%.1f%% CO2=%d TVOC=%d HCHO=%d Light=%d",
             data->sht30_valid ? data->temperature : 25.0,
             data->sht30_valid ? data->humidity : 50.0,
             data->tvoc_valid ? data->eco2 : 0,
             data->tvoc_valid ? data->tvoc : 0,
             data->tvoc_valid ? data->hcho : 0,
             light_value);

    // 4. 配置HTTP客户端
    esp_http_client_config_t config = {
        .url = SENSOR_SERVER_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
        .buffer_size = 2048,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "HTTP客户端初始化失败");
        free(json_string);
        return ESP_FAIL;
    }

    // 5. 设置请求头
    esp_http_client_set_header(client, "Content-Type", "application/json");

    // 6. 设置POST数据
    esp_http_client_set_post_field(client, json_string, strlen(json_string));

    // 7. 执行请求
    esp_err_t err = esp_http_client_perform(client);

    if (err == ESP_OK) {
        int status_code = esp_http_client_get_status_code(client);
        ESP_LOGI(TAG, "📥 HTTP状态码: %d", status_code);

        if (status_code >= 200 && status_code < 300) {
            ESP_LOGI(TAG, "✅ 数据上报成功！");
            char response[256];
            int len = esp_http_client_read_response(client, response, sizeof(response) - 1);
            if (len > 0) {
                response[len] = '\0';
                ESP_LOGI(TAG, "📄 服务器响应: %s", response);
            }
        } else if (status_code == 422) {
            ESP_LOGE(TAG, "❌ 数据格式错误 (422)");
            char response[256];
            int len = esp_http_client_read_response(client, response, sizeof(response) - 1);
            if (len > 0) {
                response[len] = '\0';
                ESP_LOGE(TAG, "错误详情: %s", response);
            }
            err = ESP_FAIL;
        } else {
            ESP_LOGE(TAG, "❌ 服务器错误: %d", status_code);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGE(TAG, "❌ HTTP请求失败: %s", esp_err_to_name(err));
        if (err == ESP_ERR_HTTP_CONNECT) {
            ESP_LOGE(TAG, "   🔍 请检查: ESP32和服务器是否在同一WiFi网络");
        }
    }

    // 8. 清理资源
    esp_http_client_cleanup(client);
    free(json_string);

    return err;
}
