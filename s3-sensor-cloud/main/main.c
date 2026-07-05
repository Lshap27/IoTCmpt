#include <string.h>

#include "actuators.h"
#include "app_config.h"
#include "app_status.h"
#include "backend_upload.h"
#include "camera_app.h"
#include "cloud_client.h"
#include "commands.h"
#include "control_state.h"
#include "display.h"
#include "esp_camera.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "fusion.h"
#include "inputs.h"
#include "sdkconfig.h"
#include "sensors.h"
#include "wifi_app.h"

static const char *TAG = "APP";

static app_config_t s_config;
static app_status_t s_status;
static sensor_sample_t s_latest_sample;
static fusion_state_t s_latest_fusion;
static cloud_command_t s_latest_command;
static SemaphoreHandle_t s_latest_mutex;
static SemaphoreHandle_t s_command_mutex;

static app_status_link_t link_status_from_result(esp_err_t result)
{
    return result == ESP_OK ? APP_STATUS_LINK_READY : APP_STATUS_LINK_DEGRADED;
}

static const char *fusion_air_quality_log_name(fusion_air_quality_t quality)
{
    switch (quality) {
    case FUSION_AIR_QUALITY_GOOD:
        return "良好";
    case FUSION_AIR_QUALITY_WATCH:
        return "关注";
    case FUSION_AIR_QUALITY_ALERT:
        return "报警";
    case FUSION_AIR_QUALITY_UNKNOWN:
    default:
        return "未知";
    }
}

static void latest_update(const sensor_sample_t *sample, const fusion_state_t *fusion)
{
    if (s_latest_mutex && xSemaphoreTake(s_latest_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_latest_sample = *sample;
        s_latest_fusion = *fusion;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_latest_sample = *sample;
        s_latest_fusion = *fusion;
    }
}

static void latest_get(sensor_sample_t *sample, fusion_state_t *fusion, app_status_t *status)
{
    if (s_latest_mutex && xSemaphoreTake(s_latest_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        *sample = s_latest_sample;
        *fusion = s_latest_fusion;
        *status = s_status;
        xSemaphoreGive(s_latest_mutex);
    } else {
        *sample = s_latest_sample;
        *fusion = s_latest_fusion;
        *status = s_status;
    }
}

static void latest_command_set(const cloud_command_t *command)
{
    if (!command) {
        return;
    }

    if (s_command_mutex && xSemaphoreTake(s_command_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_latest_command = *command;
        xSemaphoreGive(s_command_mutex);
    } else {
        s_latest_command = *command;
    }
}

static void latest_command_take(cloud_command_t *command)
{
    if (!command) {
        return;
    }

    if (s_command_mutex && xSemaphoreTake(s_command_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        *command = s_latest_command;
        command_clear(&s_latest_command);
        xSemaphoreGive(s_command_mutex);
    } else {
        *command = s_latest_command;
        command_clear(&s_latest_command);
    }
}

static void app_loop_task(void *arg)
{
    (void)arg;

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        cloud_command_t command;
        command_clear(&command);

        s_status.loop_count++;
        s_status.last_sensor_result = sensors_read(&sample);
        if (s_status.last_sensor_result != ESP_OK) {
            ESP_LOGW(TAG, "跳过传感器读取：%s", esp_err_to_name(s_status.last_sensor_result));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        esp_err_t err = fusion_evaluate(&sample, &fusion);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "数据融合失败：%s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        latest_update(&sample, &fusion);

        ESP_LOGI(
            TAG,
            "第 %lu 次采样：空气质量=%s，原因=%s",
            (unsigned long)s_status.loop_count,
            fusion_air_quality_log_name(fusion.air_quality),
            fusion.reason
        );
        ESP_LOGI(
            TAG,
            "传感器字段：温湿度=%d %.1fC %.1f%% 空气=%d TVOC=%u HCHO=%u eCO2=%u 光照=%d 偏暗=%d",
            sample.climate_valid,
            sample.temperature_c,
            sample.humidity_percent,
            sample.air_valid,
            sample.tvoc_ppb,
            sample.hcho_ug_m3,
            sample.eco2_ppm,
            sample.light_valid,
            sample.light_is_dark
        );

        err = backend_upload_sensor(&sample, &fusion);
        if (err != ESP_OK && err != ESP_ERR_INVALID_STATE && err != ESP_ERR_NOT_FOUND) {
            ESP_LOGW(TAG, "普通后端传感器上传失败：%s", esp_err_to_name(err));
        }

        s_status.last_cloud_result = cloud_send_state(&sample, &fusion, &command);
        if (s_status.last_cloud_result == ESP_ERR_INVALID_STATE) {
            s_status.cloud = APP_STATUS_LINK_DISABLED;
            command_clear(&command);
        } else {
            s_status.cloud = link_status_from_result(s_status.last_cloud_result);
        }
        latest_command_set(&command);

        vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
    }
}

static void actuator_task(void *arg)
{
    (void)arg;

    esp_err_t err = actuator_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "跳过执行器初始化：%s", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        app_status_t status;
        cloud_command_t command;
        latest_get(&sample, &fusion, &status);
        latest_command_take(&command);
        (void)sample;
        (void)status;

        s_status.last_command_result = actuator_apply(&command, &fusion);
        if (s_status.last_command_result != ESP_OK && s_status.last_command_result != ESP_ERR_INVALID_STATE) {
            ESP_LOGW(TAG, "执行器应用状态失败：%s", esp_err_to_name(s_status.last_command_result));
        }

        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

static void display_task(void *arg)
{
    (void)arg;

    esp_err_t err = display_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "跳过显示屏初始化：%s", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        app_status_t status;
        latest_get(&sample, &fusion, &status);
        display_render(&sample, &fusion, &status);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void camera_upload_task(void *arg)
{
    (void)arg;

    int capture_failures = 0;
    int upload_failures = 0;

    while (camera_app_init() != ESP_OK) {
        ESP_LOGW(TAG, "摄像头初始化失败，稍后重试");
        vTaskDelay(pdMS_TO_TICKS(10000));
    }

    while (true) {
        camera_fb_t *frame = camera_app_capture();
        if (!frame) {
            capture_failures++;
            if (capture_failures == 5) {
                ESP_LOGI(TAG, "摄像头连续采集失败，正在重新初始化");
                esp_camera_deinit();
                while (camera_app_init() != ESP_OK) {
                    vTaskDelay(pdMS_TO_TICKS(10000));
                }
                capture_failures = 0;
            }
            vTaskDelay(pdMS_TO_TICKS(10000));
            continue;
        }

        capture_failures = 0;

        esp_err_t err = backend_upload_jpeg(s_config.image_upload_url, frame->buf, frame->len);
        if (err == ESP_OK) {
            upload_failures = 0;
            ESP_LOGI(TAG, "图片上传成功");
        } else if (err != ESP_ERR_INVALID_STATE && err != ESP_ERR_INVALID_ARG) {
            upload_failures++;
            if (upload_failures == 1 || upload_failures % 30 == 0) {
                ESP_LOGW(TAG, "图片上传已失败 %d 次：%s", upload_failures, esp_err_to_name(err));
            }
        }

        err = backend_upload_jpeg(s_config.pose_upload_url, frame->buf, frame->len);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "姿态检测上传成功");
        } else if (err != ESP_ERR_INVALID_STATE && err != ESP_ERR_INVALID_ARG) {
            ESP_LOGW(TAG, "姿态检测上传失败：%s", esp_err_to_name(err));
        }

        camera_app_return_frame(frame);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

void app_main(void)
{
    memset(&s_status, 0, sizeof(s_status));
    memset(&s_latest_sample, 0, sizeof(s_latest_sample));
    memset(&s_latest_fusion, 0, sizeof(s_latest_fusion));
    command_clear(&s_latest_command);
    s_status.wifi = APP_STATUS_LINK_DISABLED;
    s_status.cloud = APP_STATUS_LINK_DISABLED;

    ESP_ERROR_CHECK(app_config_load(&s_config));
    ESP_ERROR_CHECK(control_state_init());

    s_latest_mutex = xSemaphoreCreateMutex();
    s_command_mutex = xSemaphoreCreateMutex();
    if (!s_latest_mutex || !s_command_mutex) {
        ESP_LOGE(TAG, "创建应用互斥锁失败");
        return;
    }

    esp_err_t err = sensors_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "传感器层处于降级状态：%s", esp_err_to_name(err));
    }
    s_status.last_sensor_result = err;

    err = wifi_app_connect(&s_config);
    if (err == ESP_ERR_INVALID_STATE) {
        s_status.wifi = APP_STATUS_LINK_DISABLED;
    } else {
        s_status.wifi = link_status_from_result(err);
    }

    ESP_ERROR_CHECK(cloud_client_init(&s_config));
    ESP_ERROR_CHECK(backend_upload_init(&s_config));
    s_status.cloud = s_config.cloud_enabled ? APP_STATUS_LINK_DEGRADED : APP_STATUS_LINK_DISABLED;

    err = inputs_start();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "输入任务启动失败：%s", esp_err_to_name(err));
    }

    BaseType_t ok = xTaskCreate(app_loop_task, "app_loop", 8192, NULL, 5, NULL);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "启动主循环任务失败");
    }

    if (CONFIG_APP_DISPLAY_ENABLED) {
        ok = xTaskCreate(display_task, "display_task", 4096, NULL, 4, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "启动显示屏任务失败");
        }
    }

    if (CONFIG_APP_ACTUATOR_ENABLED) {
        ok = xTaskCreate(actuator_task, "actuator_task", 4096, NULL, 4, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "启动执行器任务失败");
        }
    }

    if (CONFIG_APP_CAMERA_ENABLED) {
        ok = xTaskCreate(camera_upload_task, "camera_task", 4096, NULL, 2, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "启动摄像头任务失败");
        }
    }

    ESP_LOGI(TAG, "系统启动完成");
}
