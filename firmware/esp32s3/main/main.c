#include "app_config.h"
#include "mqtt_app.h"

#include <string.h>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "AIOT_FW";
static const int WIFI_CONNECTED_BIT = BIT0;

static app_config_t s_config;
static EventGroupHandle_t s_wifi_events;

static void on_command(const mqtt_app_command_t *command)
{
    ESP_LOGI(TAG, "command handler type=%s", command && command->type ? command->type : "");
    mqtt_app_publish_command_ack(command, "executed", "mock firmware command handler");
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    (void)arg;
    (void)event_data;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ESP_LOGI(TAG, "Wi-Fi connected");
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static esp_err_t wifi_start(void)
{
    if (!s_config.wifi_enabled) {
        ESP_LOGW(TAG, "Wi-Fi disabled");
        return ESP_ERR_INVALID_STATE;
    }
    if (s_config.wifi_ssid[0] == '\0') {
        ESP_LOGW(TAG, "Wi-Fi SSID is empty");
        return ESP_ERR_INVALID_STATE;
    }

    s_wifi_events = xEventGroupCreate();
    if (!s_wifi_events) {
        return ESP_ERR_NO_MEM;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));

    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, s_config.wifi_ssid, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, s_config.wifi_password, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, pdMS_TO_TICKS(15000));
    return (bits & WIFI_CONNECTED_BIT) ? ESP_OK : ESP_ERR_TIMEOUT;
}

static void telemetry_task(void *arg)
{
    (void)arg;

    while (true) {
        esp_err_t err = mqtt_app_publish_telemetry();
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "mock telemetry published");
        } else {
            ESP_LOGI(TAG, "mock telemetry ready but MQTT unavailable: %s", esp_err_to_name(err));
        }
        vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
    }
}

void app_main(void)
{
    app_config_load(&s_config);

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    err = wifi_start();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "Wi-Fi not ready: %s", esp_err_to_name(err));
    }

    ESP_ERROR_CHECK(mqtt_app_set_command_handler(on_command));
    err = mqtt_app_init(&s_config);
    if (err == ESP_OK && s_config.wifi_enabled && s_config.mqtt_enabled) {
        err = mqtt_app_start();
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "MQTT start failed: %s", esp_err_to_name(err));
        }
    }

    xTaskCreate(telemetry_task, "telemetry", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "AIoT firmware shell started device_id=%s", s_config.device_id);
}
