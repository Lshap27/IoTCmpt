#include "camera_app.h"

#include "app_config_defaults.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "CAMERA";

static esp_err_t camera_init_once(void) {
    gpio_config_t sccb_conf = {
        .pin_bit_mask = (1ULL << CONFIG_APP_CAMERA_SIOD_GPIO) | (1ULL << CONFIG_APP_CAMERA_SIOC_GPIO),
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&sccb_conf);

    vTaskDelay(pdMS_TO_TICKS(300));

    camera_config_t config = {
        .pin_pwdn = CONFIG_APP_CAMERA_PWDN_GPIO,
        .pin_reset = -1,
        .pin_xclk = -1,
        .pin_sccb_sda = CONFIG_APP_CAMERA_SIOD_GPIO,
        .pin_sccb_scl = CONFIG_APP_CAMERA_SIOC_GPIO,
        .pin_d7 = CONFIG_APP_CAMERA_D7_GPIO,
        .pin_d6 = CONFIG_APP_CAMERA_D6_GPIO,
        .pin_d5 = CONFIG_APP_CAMERA_D5_GPIO,
        .pin_d4 = CONFIG_APP_CAMERA_D4_GPIO,
        .pin_d3 = CONFIG_APP_CAMERA_D3_GPIO,
        .pin_d2 = CONFIG_APP_CAMERA_D2_GPIO,
        .pin_d1 = CONFIG_APP_CAMERA_D1_GPIO,
        .pin_d0 = CONFIG_APP_CAMERA_D0_GPIO,
        .pin_vsync = CONFIG_APP_CAMERA_VSYNC_GPIO,
        .pin_href = CONFIG_APP_CAMERA_HREF_GPIO,
        .pin_pclk = CONFIG_APP_CAMERA_PCLK_GPIO,
        .xclk_freq_hz = 10000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_CIF,
        .jpeg_quality = 8,
        .fb_count = 1,
        .fb_location = CAMERA_FB_IN_DRAM,
        .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
    };

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor) {
        sensor->set_contrast(sensor, 0);
        sensor->set_brightness(sensor, 0);
        sensor->set_whitebal(sensor, 1);
        sensor->set_exposure_ctrl(sensor, 1);
        sensor->set_gain_ctrl(sensor, 1);
        sensor->set_bpc(sensor, 1);
        sensor->set_wpc(sensor, 1);
        sensor->set_gainceiling(sensor, GAINCEILING_4X);
        ESP_LOGI(TAG, "摄像头传感器 PID：0x%02x", sensor->id.PID);
    }

    return ESP_OK;
}

esp_err_t camera_app_init(void) {
    if (!CONFIG_APP_CAMERA_ENABLED) {
        ESP_LOGW(TAG, "摄像头已禁用");
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = ESP_FAIL;
    for (int attempt = 1; attempt <= 3; attempt++) {
        ESP_LOGI(TAG, "摄像头初始化尝试 %d/3", attempt);
        err = camera_init_once();
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "摄像头初始化成功");
            return ESP_OK;
        }

        ESP_LOGW(TAG, "摄像头初始化失败：%s", esp_err_to_name(err));
        esp_camera_deinit();
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    return err;
}

camera_fb_t *camera_app_capture(void) {
    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame) {
        ESP_LOGW(TAG, "摄像头采集失败");
        return NULL;
    }

    ESP_LOGI(TAG, "已采集图像：长度=%u 宽=%u 高=%u 格式=%u", (unsigned int)frame->len, (unsigned int)frame->width,
             (unsigned int)frame->height, (unsigned int)frame->format);
    return frame;
}

void camera_app_return_frame(camera_fb_t *frame) {
    if (frame) {
        esp_camera_fb_return(frame);
    }
}
