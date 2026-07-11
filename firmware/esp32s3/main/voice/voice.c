#include "voice.h"

#include <stdint.h>
#include <stdio.h>

#include "app_config_defaults.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sensors.h"

static const char *TAG = "VOICE";
static SemaphoreHandle_t s_mutex;

typedef enum {
    VOICE_IDLE = 0,
    VOICE_AIR_BAD,
    VOICE_SMOKE,
} voice_state_t;

static voice_state_t s_state;

static const uint8_t GB_SMOKE_ALARM[] = {0xD1, 0xCC, 0xCE, 0xED, 0xC5, 0xA8, 0xB6, 0xC8, 0xB3, 0xAC, 0xB1, 0xEA};
static const uint8_t GB_AIR_BAD[] = {0xBF, 0xD5, 0xC6, 0xF8, 0xD6, 0xCA, 0xC1, 0xBF, 0xBD, 0xCF, 0xB2,
                                     0xEE, 0xA3, 0xAC, 0xBD, 0xA8, 0xD2, 0xE9, 0xBF, 0xAA, 0xB4, 0xB0};

static bool wait_idle(uint32_t timeout_ms) {
    const TickType_t start = xTaskGetTickCount();
    while ((xTaskGetTickCount() - start) * portTICK_PERIOD_MS < timeout_ms) {
        if (gpio_get_level(CONFIG_APP_SYN6288_BY_GPIO) == 0) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return false;
}

static void speak(const uint8_t *text, size_t text_len) {
    if (!wait_idle(5000) || !sensors_air_uart_lock(1000)) {
        ESP_LOGW(TAG, "SYN6288 busy, skipping announcement");
        return;
    }

    uint8_t frame[96];
    size_t index = 0;
    const uint16_t data_len = (uint16_t)(4 + text_len);
    const uint16_t payload_len = (uint16_t)(2 + data_len);
    frame[index++] = 0xFD;
    frame[index++] = (payload_len >> 8) & 0xFF;
    frame[index++] = payload_len & 0xFF;
    frame[index++] = 0x01;
    frame[index++] = 0x00;
    frame[index++] = 0x0A;
    frame[index++] = 0x05;
    frame[index++] = 0x05;
    for (size_t i = 0; i < text_len; i++) {
        frame[index++] = text[i];
    }
    uint8_t checksum = 0;
    for (size_t i = 0; i < index; i++) {
        checksum ^= frame[i];
    }
    frame[index++] = checksum;
    uart_write_bytes((uart_port_t)CONFIG_APP_TVOC_UART_NUM, frame, index);
    sensors_air_uart_unlock();
}

esp_err_t voice_init(void) {
    if (!CONFIG_APP_VOICE_ENABLED) {
        return ESP_ERR_INVALID_STATE;
    }
    gpio_config_t by = {
        .pin_bit_mask = 1ULL << CONFIG_APP_SYN6288_BY_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&by);
    s_mutex = xSemaphoreCreateMutex();
    if (!s_mutex) {
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "SYN6288 BY=GPIO%d，共用 UART%d TX", CONFIG_APP_SYN6288_BY_GPIO, CONFIG_APP_TVOC_UART_NUM);
    return ESP_OK;
}

void voice_update(bool smoke_detected, bool air_bad) {
    if (!CONFIG_APP_VOICE_ENABLED || !s_mutex || xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) != pdTRUE) {
        return;
    }
    const voice_state_t next = smoke_detected ? VOICE_SMOKE : air_bad ? VOICE_AIR_BAD : VOICE_IDLE;
    if (next != s_state) {
        s_state = next;
        if (next == VOICE_SMOKE) {
            speak(GB_SMOKE_ALARM, sizeof(GB_SMOKE_ALARM));
        } else if (next == VOICE_AIR_BAD) {
            speak(GB_AIR_BAD, sizeof(GB_AIR_BAD));
        }
    }
    xSemaphoreGive(s_mutex);
}
