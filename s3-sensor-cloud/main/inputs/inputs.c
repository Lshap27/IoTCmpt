#include "inputs.h"

#include "control_state.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "INPUTS";

static void button_task(void *arg)
{
    (void)arg;

    bool last_pressed = false;
    while (true) {
        const bool pressed = gpio_get_level(CONFIG_APP_BUTTON_GPIO) == 0;
        if (pressed && !last_pressed) {
            vTaskDelay(pdMS_TO_TICKS(20));
            if (gpio_get_level(CONFIG_APP_BUTTON_GPIO) == 0) {
                ESP_LOGI(TAG, "Manual button toggled window state");
                control_state_toggle_manual_window();
            }
        }
        last_pressed = pressed;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

esp_err_t inputs_start(void)
{
    if (!CONFIG_APP_BUTTON_ENABLED) {
        ESP_LOGW(TAG, "Button input disabled");
        return ESP_ERR_INVALID_STATE;
    }

    gpio_config_t key_cfg = {
        .pin_bit_mask = 1ULL << CONFIG_APP_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&key_cfg);

    BaseType_t ok = xTaskCreate(button_task, "button_task", 3072, NULL, 2, NULL);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
