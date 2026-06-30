#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define STATUS_LED_GPIO GPIO_NUM_2
#define SAMPLE_PERIOD_MS 60000

static const char *TAG = "s3_sensor_cloud";

typedef struct {
    float temperature_c;
    float humidity_percent;
    uint32_t light_raw;
} sensor_sample_t;

static esp_err_t status_led_init(void)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << STATUS_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    return gpio_config(&io_conf);
}

static void status_led_set(bool on)
{
    gpio_set_level(STATUS_LED_GPIO, on ? 1 : 0);
}

static void wifi_init_placeholder(void)
{
    ESP_LOGI(TAG, "TODO: initialize Wi-Fi with project credentials from local configuration");
}

static sensor_sample_t sensor_read_placeholder(void)
{
    static uint32_t counter;
    counter++;

    sensor_sample_t sample = {
        .temperature_c = 24.0f + (float)(counter % 5),
        .humidity_percent = 55.0f + (float)(counter % 7),
        .light_raw = 900 + counter * 3,
    };

    return sample;
}

static char *build_llm_payload(const sensor_sample_t *sample)
{
    cJSON *root = cJSON_CreateObject();
    cJSON *sensor = cJSON_CreateObject();

    if (root == NULL || sensor == NULL) {
        cJSON_Delete(root);
        cJSON_Delete(sensor);
        return NULL;
    }

    cJSON_AddStringToObject(root, "device", "esp32-s3-devkitc-1");
    cJSON_AddStringToObject(root, "scenario", "sensor_cloud_control");
    cJSON_AddItemToObject(root, "sensor", sensor);
    cJSON_AddNumberToObject(sensor, "temperature_c", sample->temperature_c);
    cJSON_AddNumberToObject(sensor, "humidity_percent", sample->humidity_percent);
    cJSON_AddNumberToObject(sensor, "light_raw", sample->light_raw);
    cJSON_AddStringToObject(root, "request", "Analyze sensor state and return a compact device command.");

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return payload;
}

static esp_err_t cloud_llm_exchange_placeholder(const char *payload, char *command, size_t command_size)
{
    if (payload == NULL || command == NULL || command_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_LOGI(TAG, "TODO: POST payload to configured cloud LLM endpoint using esp_http_client");
    ESP_LOGI(TAG, "Payload: %s", payload);

    const char *placeholder_command = "led:on";
    strlcpy(command, placeholder_command, command_size);
    return ESP_OK;
}

static void apply_cloud_command(const char *command)
{
    if (command == NULL) {
        return;
    }

    if (strcmp(command, "led:on") == 0) {
        status_led_set(true);
        ESP_LOGI(TAG, "Applied cloud command: LED on");
    } else if (strcmp(command, "led:off") == 0) {
        status_led_set(false);
        ESP_LOGI(TAG, "Applied cloud command: LED off");
    } else {
        ESP_LOGW(TAG, "Unhandled cloud command: %s", command);
    }
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    ESP_ERROR_CHECK(status_led_init());

    wifi_init_placeholder();

    while (true) {
        sensor_sample_t sample = sensor_read_placeholder();
        char *payload = build_llm_payload(&sample);

        if (payload == NULL) {
            ESP_LOGE(TAG, "Failed to build LLM payload");
            vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
            continue;
        }

        char command[32] = {0};
        ret = cloud_llm_exchange_placeholder(payload, command, sizeof(command));
        free(payload);

        if (ret == ESP_OK) {
            apply_cloud_command(command);
        } else {
            ESP_LOGE(TAG, "Cloud exchange failed: %s", esp_err_to_name(ret));
        }

        vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
    }
}

