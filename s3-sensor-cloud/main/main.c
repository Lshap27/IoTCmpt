#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "camera_app.h"
#include "wifi_app.h"

static const char *TAG = "MAIN";

#define WIFI_SSID      "lnmot"
#define WIFI_PASSWORD  "abcabc88"

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
        camera_app_capture_once();
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}