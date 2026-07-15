#include "voice.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "app_config_defaults.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "firmware_behavior.generated.h"
#include "mbedtls/base64.h"
#include "sensors.h"
static const char *TAG = "VOICE";
static SemaphoreHandle_t s_mutex;
static QueueHandle_t s_announcement_queue;
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_pending_mask;
static bool s_smoke_active;
static bool s_smoke_silenced;

#define ANNOUNCEMENT_QUEUE_LENGTH 4

/* “警告，检测到烟雾，请立即撤离并检查现场火源，确保人身安全。” */
static const char *SMOKE_ANNOUNCEMENT_BASE64 =
    "vq+45qOsvOyy4rW90czO7aOsx+vBory0s7fA67KivOyy6c/Ws6G78NS0o6zIt7GjyMvJ7bCyyKuhow==";
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
    if (!wait_idle(5000)) {
        ESP_LOGW(TAG, "SYN6288 BY busy timeout");
        return ESP_ERR_TIMEOUT;
    }
    if (!sensors_air_uart_lock(1000)) {
        ESP_LOGW(TAG, "SYN6288 UART lock timeout");
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
    if (written != (int)index) {
        ESP_LOGW(TAG, "SYN6288 UART write failed expected=%u actual=%d", (unsigned)index, written);
        sensors_air_uart_unlock();
        return ESP_FAIL;
    }
    const esp_err_t tx_result =
        uart_wait_tx_done((uart_port_t)CONFIG_APP_TVOC_UART_NUM, pdMS_TO_TICKS(AIOT_VOICE_TX_TIMEOUT_MS));
    sensors_air_uart_unlock();
    if (tx_result != ESP_OK) {
        ESP_LOGW(TAG, "SYN6288 UART TX completion timeout: %s", esp_err_to_name(tx_result));
        return tx_result == ESP_ERR_TIMEOUT ? ESP_ERR_TIMEOUT : ESP_FAIL;
    }
    return ESP_OK;
}

static const char *announcement_payload(voice_announcement_t announcement) {
    switch (announcement) {
    case VOICE_ANNOUNCEMENT_SMOKE:
        return SMOKE_ANNOUNCEMENT_BASE64;
    default:
        return NULL;
    }
}

static void announcement_task(void *arg) {
    (void)arg;
    voice_announcement_t announcement;
    while (true) {
        if (xQueueReceive(s_announcement_queue, &announcement, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        esp_err_t err = ESP_ERR_INVALID_ARG;
        for (uint32_t attempt = 0; attempt < AIOT_VOICE_LOCAL_RETRY_ATTEMPTS; attempt++) {
            bool suppressed = false;
            if (announcement == VOICE_ANNOUNCEMENT_SMOKE) {
                portENTER_CRITICAL(&s_state_lock);
                suppressed = !s_smoke_active || s_smoke_silenced;
                portEXIT_CRITICAL(&s_state_lock);
            }
            if (suppressed) {
                ESP_LOGI(TAG, "烟雾已解除或静音，取消待播语音");
                err = ESP_ERR_INVALID_STATE;
                break;
            }
            const char *encoded = announcement_payload(announcement);
            err = encoded ? voice_speak_base64(encoded) : ESP_ERR_INVALID_ARG;
            if (err == ESP_OK || (err != ESP_ERR_TIMEOUT && err != ESP_FAIL)) {
                break;
            }
            if (attempt + 1 < AIOT_VOICE_LOCAL_RETRY_ATTEMPTS) {
                const uint32_t delay_ms = AIOT_VOICE_RETRY_BACKOFF_MS << attempt;
                ESP_LOGW(TAG, "本地语音重试 type=%d attempt=%u delay_ms=%u error=%s", (int)announcement,
                         (unsigned)(attempt + 2), (unsigned)delay_ms, esp_err_to_name(err));
                vTaskDelay(pdMS_TO_TICKS(delay_ms));
            }
        }
        portENTER_CRITICAL(&s_state_lock);
        s_pending_mask &= ~(1U << (uint32_t)announcement);
        portEXIT_CRITICAL(&s_state_lock);
        if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
            ESP_LOGW(TAG, "本地语音播报失败 type=%d: %s", (int)announcement, esp_err_to_name(err));
        }
    }
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
    s_announcement_queue = xQueueCreate(ANNOUNCEMENT_QUEUE_LENGTH, sizeof(voice_announcement_t));
    if (!s_announcement_queue) {
        vSemaphoreDelete(s_mutex);
        s_mutex = NULL;
        return ESP_ERR_NO_MEM;
    }
    if (xTaskCreate(announcement_task, "voice_announce", 3072, NULL, 5, NULL) != pdPASS) {
        vQueueDelete(s_announcement_queue);
        vSemaphoreDelete(s_mutex);
        s_announcement_queue = NULL;
        s_mutex = NULL;
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
    /* 本地和 MQTT 语音共用发送通道；允许等待当前短句结束，避免安全播报因互斥竞争直接丢失。 */
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(6000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    esp_err_t err = speak(decoded, decoded_len);
    xSemaphoreGive(s_mutex);
    return err;
}

esp_err_t voice_announce(voice_announcement_t announcement) {
    if (!CONFIG_APP_VOICE_ENABLED || !s_announcement_queue || !announcement_payload(announcement)) {
        return ESP_ERR_INVALID_STATE;
    }
    const uint32_t pending_bit = 1U << (uint32_t)announcement;
    portENTER_CRITICAL(&s_state_lock);
    if ((s_pending_mask & pending_bit) != 0U) {
        portEXIT_CRITICAL(&s_state_lock);
        return ESP_OK;
    }
    s_pending_mask |= pending_bit;
    portEXIT_CRITICAL(&s_state_lock);

    BaseType_t queued = announcement == VOICE_ANNOUNCEMENT_SMOKE
                            ? xQueueSendToFront(s_announcement_queue, &announcement, 0)
                            : xQueueSendToBack(s_announcement_queue, &announcement, 0);
    if (queued != pdTRUE && announcement == VOICE_ANNOUNCEMENT_SMOKE) {
        /* 队列满时丢弃一条较早的普通播报，为烟雾安全告警让位。 */
        voice_announcement_t dropped;
        if (xQueueReceive(s_announcement_queue, &dropped, 0) == pdTRUE) {
            portENTER_CRITICAL(&s_state_lock);
            s_pending_mask &= ~(1U << (uint32_t)dropped);
            portEXIT_CRITICAL(&s_state_lock);
        }
        queued = xQueueSendToFront(s_announcement_queue, &announcement, 0);
    }
    if (queued != pdTRUE) {
        portENTER_CRITICAL(&s_state_lock);
        s_pending_mask &= ~pending_bit;
        portEXIT_CRITICAL(&s_state_lock);
    }
    return queued == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
}

void voice_set_smoke_state(bool active, bool silenced) {
    portENTER_CRITICAL(&s_state_lock);
    s_smoke_active = active;
    s_smoke_silenced = silenced;
    portEXIT_CRITICAL(&s_state_lock);
}
