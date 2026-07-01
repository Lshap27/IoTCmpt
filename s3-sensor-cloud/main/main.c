#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "camera_app.h"

static const char *TAG = "MAIN";

void app_main(void)
{
    ESP_LOGI(TAG, "App start");

    if (camera_app_init() != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed");
        return;
    }

    while (1) {
        camera_app_capture_once();
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}