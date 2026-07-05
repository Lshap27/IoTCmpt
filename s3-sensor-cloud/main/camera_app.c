#include "camera_app.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

#include "camera_pins.h"

static const char *TAG = "CAM_APP";

static esp_err_t camera_init_once(void)
{
    /* 传感器上电稳定延时 —— 解决 PID=0x0 */
    vTaskDelay(pdMS_TO_TICKS(300));

    camera_config_t config = {
        .pin_pwdn  = CAM_PIN_PWDN,
        .pin_reset = CAM_PIN_RESET,

        .pin_xclk = CAM_PIN_XCLK,

        .pin_sccb_sda = CAM_PIN_SIOD,
        .pin_sccb_scl = CAM_PIN_SIOC,

        .pin_d7 = CAM_PIN_D7,
        .pin_d6 = CAM_PIN_D6,
        .pin_d5 = CAM_PIN_D5,
        .pin_d4 = CAM_PIN_D4,
        .pin_d3 = CAM_PIN_D3,
        .pin_d2 = CAM_PIN_D2,
        .pin_d1 = CAM_PIN_D1,
        .pin_d0 = CAM_PIN_D0,

        .pin_vsync = CAM_PIN_VSYNC,
        .pin_href  = CAM_PIN_HREF,
        .pin_pclk  = CAM_PIN_PCLK,

        .xclk_freq_hz = 10000000,   // 先用 10MHz 确保 SCCB 稳定

        .ledc_timer   = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,

        .pixel_format = PIXFORMAT_JPEG,
        .frame_size   = FRAMESIZE_QVGA,
        .jpeg_quality = 8,

        .fb_count    = 1,
        .fb_location = CAMERA_FB_IN_DRAM,
        .grab_mode   = CAMERA_GRAB_WHEN_EMPTY,
    };

    ESP_LOGI(TAG, "Initializing camera...");
    ESP_LOGI(TAG, "XCLK=%d SIOD=%d SIOC=%d PCLK=%d VSYNC=%d HREF=%d",
             CAM_PIN_XCLK, CAM_PIN_SIOD, CAM_PIN_SIOC,
             CAM_PIN_PCLK, CAM_PIN_VSYNC, CAM_PIN_HREF);

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        return err;
    }

    /* Optimize sensor: contrast+, brightness+, denoise */
    sensor_t *s = esp_camera_sensor_get();
    if (s) {
        s->set_contrast(s, 1);
        s->set_brightness(s, 1);
        s->set_bpc(s, 1);
        s->set_wpc(s, 1);
        s->set_gainceiling(s, GAINCEILING_4X);
    }

    return ESP_OK;
}

esp_err_t camera_app_init(void)
{
    esp_err_t err = ESP_FAIL;

    for (int i = 1; i <= 3; i++) {
        ESP_LOGI(TAG, "Camera init attempt %d/3", i);

        err = camera_init_once();

        if (err == ESP_OK) {
            ESP_LOGI(TAG, "Camera init success");

            sensor_t *s = esp_camera_sensor_get();
            if (s) {
                ESP_LOGI(TAG, "Camera sensor PID: 0x%02x", s->id.PID);
            }

            return ESP_OK;
        }

        ESP_LOGE(TAG, "Camera init failed: 0x%x", err);

        esp_camera_deinit();
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    return err;
}

camera_fb_t *camera_app_capture(void)
{
    camera_fb_t *fb = esp_camera_fb_get();

    if (!fb) {
        ESP_LOGE(TAG, "Camera capture failed");
        return NULL;
    }

    ESP_LOGI(TAG, "Captured frame: len=%d bytes, width=%d, height=%d, format=%d",
             fb->len, fb->width, fb->height, fb->format);

    return fb;
}

void camera_app_return_frame(camera_fb_t *fb)
{
    if (fb) {
        esp_camera_fb_return(fb);
    }
}

esp_err_t camera_app_capture_once(void)
{
    camera_fb_t *fb = camera_app_capture();

    if (!fb) {
        return ESP_FAIL;
    }

    camera_app_return_frame(fb);
    return ESP_OK;
}
