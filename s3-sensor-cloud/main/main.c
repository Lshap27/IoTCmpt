#include <string.h>

#include "app_config.h"
#include "app_status.h"
#include "cloud_client.h"
#include "commands.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "fusion.h"
#include "sensors.h"
#include "wifi_app.h"

static const char *TAG = "APP";

static app_config_t s_config;
static app_status_t s_status;

static app_status_link_t link_status_from_result(esp_err_t result)
{
    return result == ESP_OK ? APP_STATUS_LINK_READY : APP_STATUS_LINK_DEGRADED;
}

static void app_loop_task(void *arg)
{
    (void)arg;

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        cloud_command_t command;

        s_status.loop_count++;
        s_status.last_sensor_result = sensors_read(&sample);
        if (s_status.last_sensor_result != ESP_OK) {
            ESP_LOGW(TAG, "Sensor read skipped: %s", esp_err_to_name(s_status.last_sensor_result));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        esp_err_t err = fusion_evaluate(&sample, &fusion);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "Fusion failed: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        ESP_LOGI(
            TAG,
            "Sample #%lu quality=%s reason=%s",
            (unsigned long)s_status.loop_count,
            fusion_air_quality_name(fusion.air_quality),
            fusion.reason
        );

        s_status.last_cloud_result = cloud_send_state(&sample, &fusion, &command);
        if (s_status.last_cloud_result == ESP_ERR_INVALID_STATE) {
            s_status.cloud = APP_STATUS_LINK_DISABLED;
            command_clear(&command);
        } else {
            s_status.cloud = link_status_from_result(s_status.last_cloud_result);
        }

        s_status.last_command_result = command_apply(&command);
        if (s_status.last_command_result != ESP_OK) {
            ESP_LOGW(TAG, "Command rejected: %s", esp_err_to_name(s_status.last_command_result));
        }

        vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
    }
}

void app_main(void)
{
    memset(&s_status, 0, sizeof(s_status));
    s_status.wifi = APP_STATUS_LINK_DISABLED;
    s_status.cloud = APP_STATUS_LINK_DISABLED;

    ESP_ERROR_CHECK(app_config_load(&s_config));

    esp_err_t err = sensors_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Sensor layer is degraded: %s", esp_err_to_name(err));
    }
    s_status.last_sensor_result = err;

    err = wifi_app_connect(&s_config);
    if (err == ESP_ERR_INVALID_STATE) {
        s_status.wifi = APP_STATUS_LINK_DISABLED;
    } else {
        s_status.wifi = link_status_from_result(err);
    }

    ESP_ERROR_CHECK(cloud_client_init(&s_config));
    s_status.cloud = s_config.cloud_enabled ? APP_STATUS_LINK_DEGRADED : APP_STATUS_LINK_DISABLED;

    BaseType_t task_ok = xTaskCreate(app_loop_task, "app_loop", 8192, NULL, 5, NULL);
    if (task_ok != pdPASS) {
        ESP_LOGE(TAG, "Failed to start app loop task");
    }
}
