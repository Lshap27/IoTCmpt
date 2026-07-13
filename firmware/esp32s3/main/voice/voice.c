#include "voice.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "app_config_defaults.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "sensors.h"
static const char *TAG = "VOICE";
static SemaphoreHandle_t s_mutex;

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

static esp_err_t speak(const uint8_t *text, size_t text_len) {
    if (!wait_idle(5000) || !sensors_air_uart_lock(1000)) {
        ESP_LOGW(TAG, "SYN6288 busy, skipping announcement");
        return ESP_ERR_TIMEOUT;
    }

    if (!text || text_len == 0 || text_len > 220) {
        sensors_air_uart_unlock();
        return ESP_ERR_INVALID_SIZE;
    }
    uint8_t frame[256];
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
    const int written = uart_write_bytes((uart_port_t)CONFIG_APP_TVOC_UART_NUM, frame, index);
    sensors_air_uart_unlock();
    return written == (int)index ? ESP_OK : ESP_FAIL;
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

    /* 与 TVOC 共用 UART：模拟传感器模式下 sensors_init 不会装 UART 驱动，这里补装，
     * 否则 speak() 的 uart_write_bytes 会静默失败，语音播报永远不响 */
    if (!uart_is_driver_installed((uart_port_t)CONFIG_APP_TVOC_UART_NUM)) {
        uart_config_t uart_config = {
            .baud_rate = 9600,
            .data_bits = UART_DATA_8_BITS,
            .parity = UART_PARITY_DISABLE,
            .stop_bits = UART_STOP_BITS_1,
            .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
            .source_clk = UART_SCLK_DEFAULT,
        };
        esp_err_t err = uart_driver_install((uart_port_t)CONFIG_APP_TVOC_UART_NUM, 256, 0, 0, NULL, 0);
        if (err != ESP_OK) {
            return err;
        }
        ESP_ERROR_CHECK(uart_param_config((uart_port_t)CONFIG_APP_TVOC_UART_NUM, &uart_config));
        ESP_ERROR_CHECK(uart_set_pin((uart_port_t)CONFIG_APP_TVOC_UART_NUM, CONFIG_APP_TVOC_TX_GPIO,
                                     CONFIG_APP_TVOC_RX_GPIO, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    }

    s_mutex = xSemaphoreCreateMutex();
    if (!s_mutex) {
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "SYN6288 BY=GPIO%d，共用 UART%d TX", CONFIG_APP_SYN6288_BY_GPIO, CONFIG_APP_TVOC_UART_NUM);
    return ESP_OK;
}

esp_err_t voice_speak_base64(const char *encoded) {
    if (!CONFIG_APP_VOICE_ENABLED || !s_mutex || !encoded) {
        return ESP_ERR_INVALID_STATE;
    }
    uint8_t decoded[224];
    size_t decoded_len = 0;
    if (mbedtls_base64_decode(decoded, sizeof(decoded), &decoded_len, (const unsigned char *)encoded,
                              strlen(encoded)) != 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(100)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    esp_err_t err = speak(decoded, decoded_len);
    xSemaphoreGive(s_mutex);
    return err;
}
