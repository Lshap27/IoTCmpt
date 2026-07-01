#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "camera_app.h"
#include "wifi_app.h"
#include "http_upload.h"

static const char *TAG = "MAIN";

#define WIFI_SSID      "lnmot"
#define WIFI_PASSWORD  "abcabc88"

#define UPLOAD_URL     "http://10.208.188.133:8000/upload"

void app_main(void)
{
    ESP_LOGI(TAG, "App start");

    if (wifi_app_init_sta(WIFI_SSID, WIFI_PASSWORD) != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi init failed");
        return;
    }

    if (camera_app_init() != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed");
        return;
    }

    while (1) {
        camera_fb_t *fb = camera_app_capture();

        if (fb) {
            esp_err_t err = http_upload_jpeg(UPLOAD_URL, fb->buf, fb->len);

            if (err == ESP_OK) {
                ESP_LOGI(TAG, "Image upload success");
            } else {
                ESP_LOGE(TAG, "Image upload failed");
            }

            camera_app_return_frame(fb);
        }

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}