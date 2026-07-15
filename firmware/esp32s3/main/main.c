#include "actuators.h"
#include "app_config.h"
#include "app_config_defaults.h"
#include "app_status.h"
#include "camera_app.h"
#include "control_state.h"
#include "display.h"
#include "esp_camera.h"
#include "esp_err.h"
#include "esp_log.h"
#include "fusion.h"
#include "http_upload.h"
#include "inputs.h"
#include "mqtt_app.h"
#include "sensors.h"
#include "voice.h"

#include <string.h>

#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "firmware_behavior.generated.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"

/** TODO：
 * 1、LED灯的控制要加入可视化“固件配置”面板。
 * 2、LED灯要根据当前环境亮度，有人无人（摄像头是否检测到人）来自动控制开关。(AI自行决策)
 * 3、mideaPipe检测有人无人。
 * 4、mideaPipe目前的精度似乎不够。
 * 5、
 */

static const char *TAG = "AIOT_FW";
static const int WIFI_CONNECTED_BIT = BIT0;

static app_config_t s_config;
static app_status_t s_status;
static sensor_sample_t s_latest_sample;
static fusion_state_t s_latest_fusion;
static SemaphoreHandle_t s_latest_mutex;
static QueueHandle_t s_command_queue;
static EventGroupHandle_t s_wifi_events;

/* 队列深度和执行周期来自共享固件行为契约。 */

static app_status_link_t link_status_from_result(esp_err_t result) {
    return result == ESP_OK ? APP_STATUS_LINK_READY : APP_STATUS_LINK_DEGRADED;
}

static void latest_update(const sensor_sample_t *sample, const fusion_state_t *fusion) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_latest_sample = *sample;
        s_latest_fusion = *fusion;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_latest_sample = *sample;
        s_latest_fusion = *fusion;
    }
}

static void latest_smoke_update(bool detected, bool valid) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_latest_sample.smoke_detected = detected;
        s_latest_sample.smoke_valid = valid;
        xSemaphoreGive(s_latest_mutex);
    }
}

static void latest_get(sensor_sample_t *sample, fusion_state_t *fusion, app_status_t *status) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        *sample = s_latest_sample;
        *fusion = s_latest_fusion;
        *status = s_status;
        xSemaphoreGive(s_latest_mutex);
    } else {
        *sample = s_latest_sample;
        *fusion = s_latest_fusion;
        *status = s_status;
    }
}

/* s_status 与 latest_get 共用 s_latest_mutex，避免读取到写了一半的状态 */
static void status_note_sensor(esp_err_t result) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_status.loop_count++;
        s_status.last_sensor_result = result;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_status.loop_count++;
        s_status.last_sensor_result = result;
    }
}

static void status_set_cloud(app_status_link_t link) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_status.cloud = link;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_status.cloud = link;
    }
}

static void status_set_wifi(app_status_link_t link) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_status.wifi = link;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_status.wifi = link;
    }
}

static void status_set_command_result(esp_err_t result) {
    if (s_latest_mutex) {
        xSemaphoreTake(s_latest_mutex, portMAX_DELAY);
        s_status.last_command_result = result;
        xSemaphoreGive(s_latest_mutex);
    } else {
        s_status.last_command_result = result;
    }
}

static void on_command(const mqtt_app_command_t *command) {
    if (!command) {
        return;
    }
    ESP_LOGI(TAG, "queued command id=%s type=%s", command->command_id, command_type_name(command->command.type));
    if (!s_command_queue || xQueueSend(s_command_queue, command, 0) != pdTRUE) {
        /* 队列满：拒绝而不是覆盖，让云端立刻知道命令被丢弃 */
        ESP_LOGW(TAG, "command queue full, rejecting id=%s", command->command_id);
        mqtt_app_publish_command_ack(command, "rejected", "command queue full");
        return;
    }
    mqtt_app_publish_command_ack(command, "accepted", "queued");
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
    (void)arg;
    (void)event_data;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying");
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        status_set_wifi(APP_STATUS_LINK_DEGRADED);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ESP_LOGI(TAG, "Wi-Fi connected");
        status_set_wifi(APP_STATUS_LINK_READY);
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static esp_err_t wifi_start(void) {
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
    /* SSID 字段无需 NUL 结尾（驱动按 strnlen(ssid,32) 解析），
     * 用 strlcpy 会把合法的 32 字符 SSID 截成 31 字符导致永远连不上 */
    const size_t ssid_len = strnlen(s_config.wifi_ssid, sizeof(wifi_config.sta.ssid));
    memcpy(wifi_config.sta.ssid, s_config.wifi_ssid, ssid_len);
    strlcpy((char *)wifi_config.sta.password, s_config.wifi_password, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, pdMS_TO_TICKS(15000));
    if ((bits & WIFI_CONNECTED_BIT) == 0) {
        return ESP_ERR_TIMEOUT;
    }
    esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    esp_err_t sntp_result = esp_netif_sntp_init(&sntp);
    if (sntp_result != ESP_OK) {
        ESP_LOGW(TAG, "SNTP initialization failed: %s", esp_err_to_name(sntp_result));
    }
    return ESP_OK;
}

static void telemetry_task(void *arg) {
    (void)arg;

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;

        esp_err_t sensor_result = sensors_read(&sample);
        status_note_sensor(sensor_result);
        if (sensor_result != ESP_OK) {
            ESP_LOGW(TAG, "sensor read skipped: %s", esp_err_to_name(sensor_result));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        esp_err_t err = fusion_evaluate(&sample, &fusion);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "fusion failed: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
            continue;
        }

        latest_update(&sample, &fusion);
        err = mqtt_app_publish_telemetry(&sample, &fusion);
        if (err == ESP_OK) {
            status_set_cloud(APP_STATUS_LINK_READY);
            ESP_LOGI(TAG, "telemetry published air_quality=%s", fusion_air_quality_name(fusion.air_quality));
        } else {
            status_set_cloud(s_config.mqtt_enabled ? APP_STATUS_LINK_DEGRADED : APP_STATUS_LINK_DISABLED);
            ESP_LOGI(TAG, "telemetry ready but MQTT unavailable: %s", esp_err_to_name(err));
        }

        vTaskDelay(pdMS_TO_TICKS(s_config.sensor_interval_ms));
    }
}

static void safety_task(void *arg) {
    (void)arg;
    bool episode_active = false;
    TickType_t clear_since = 0;
    TickType_t last_announcement = 0;

    while (true) {
        bool detected = false;
        bool valid = false;
        if (sensors_read_smoke(&detected, &valid) == ESP_OK && valid) {
            const TickType_t now = xTaskGetTickCount();
            latest_smoke_update(detected, true);
            control_state_set_alarm_source(CONTROL_ALARM_SMOKE, detected);
            actuator_refresh_alarm();

            control_state_t control;
            control_state_get(&control);
            voice_set_smoke_state(episode_active || detected, control.smoke_silenced);

            if (detected) {
                clear_since = 0;
                const bool first_announcement = !episode_active;
                const bool periodic_announcement =
                    episode_active &&
                    (now - last_announcement) >= pdMS_TO_TICKS(AIOT_SMOKE_REANNOUNCE_SECONDS * 1000U);
                if (first_announcement) {
                    episode_active = true;
                    mqtt_app_publish_event("smoke.detected", "critical", "MQ-2 检测到烟雾");
                }
                if ((first_announcement || periodic_announcement) && !control.smoke_silenced) {
                    const esp_err_t voice_result = voice_announce(VOICE_ANNOUNCEMENT_SMOKE);
                    last_announcement = now;
                    if (voice_result != ESP_OK && voice_result != ESP_ERR_INVALID_STATE) {
                        ESP_LOGW(TAG, "烟雾语音入队失败: %s", esp_err_to_name(voice_result));
                    }
                }
            } else if (episode_active) {
                if (clear_since == 0) {
                    clear_since = now;
                } else if ((now - clear_since) >= pdMS_TO_TICKS(AIOT_SMOKE_CLEAR_STABLE_MS)) {
                    episode_active = false;
                    clear_since = 0;
                    last_announcement = 0;
                    control_state_clear_smoke_silence();
                    voice_set_smoke_state(false, false);
                    mqtt_app_publish_event("smoke.cleared", "info", "MQ-2 烟雾状态已解除");
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static void actuator_task(void *arg) {
    (void)arg;

    esp_err_t err = actuator_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "actuator init skipped: %s", esp_err_to_name(err));
    }

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        app_status_t status;
        mqtt_app_command_t envelope = {0};
        (void)sample;
        (void)status;

        latest_get(&sample, &fusion, &status);
        const bool has_command = s_command_queue && xQueueReceive(s_command_queue, &envelope, 0) == pdTRUE;

        if (err != ESP_OK) {
            if (has_command) {
                mqtt_app_publish_command_ack(&envelope, "rejected", "actuator disabled");
            }
            vTaskDelay(pdMS_TO_TICKS(AIOT_COMMAND_EXECUTION_PERIOD_MS));
            continue;
        }

        control_state_t before;
        control_state_get(&before);
        const esp_err_t command_result = actuator_apply(has_command ? &envelope.command : NULL, &fusion);
        status_set_command_result(command_result);
        if (!has_command && command_result == ESP_OK && before.priority == CONTROL_PRIORITY_AUTO_FIRST &&
            !before.window_open && fusion.recommend_open_window) {
            control_state_t after;
            control_state_get(&after);
            if (after.window_open) {
                const esp_err_t voice_result = voice_announce(VOICE_ANNOUNCEMENT_AIR_VENTILATION);
                if (voice_result != ESP_OK && voice_result != ESP_ERR_INVALID_STATE) {
                    ESP_LOGW(TAG, "通风语音入队失败: %s", esp_err_to_name(voice_result));
                }
            }
        }
        if (has_command) {
            const bool rejected = command_result == ESP_ERR_NOT_SUPPORTED || command_result == ESP_ERR_INVALID_ARG ||
                                  command_result == ESP_ERR_INVALID_STATE || command_result == ESP_ERR_INVALID_RESPONSE;
            const char *ack_status = command_result == ESP_OK ? "executed" : rejected ? "rejected" : "failed";
            const char *message = command_result == ESP_ERR_NOT_SUPPORTED      ? "unsupported_command"
                                  : command_result == ESP_ERR_INVALID_ARG      ? "invalid_parameter"
                                  : command_result == ESP_ERR_INVALID_STATE    ? "policy_denied"
                                  : command_result == ESP_ERR_INVALID_RESPONSE ? "safety_interlock"
                                                                               : esp_err_to_name(command_result);
            mqtt_app_publish_command_ack(&envelope, ack_status, message);
        }

        vTaskDelay(pdMS_TO_TICKS(AIOT_COMMAND_EXECUTION_PERIOD_MS));
    }
}

static void display_task(void *arg) {
    (void)arg;

    esp_err_t err = display_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "display init skipped: %s", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    while (true) {
        sensor_sample_t sample;
        fusion_state_t fusion;
        app_status_t status;
        latest_get(&sample, &fusion, &status);
        display_render(&sample, &fusion, &status);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void camera_upload_task(void *arg) {
    (void)arg;

    int capture_failures = 0;
    int upload_failures = 0;

    while (camera_app_init() != ESP_OK) {
        ESP_LOGW(TAG, "camera init failed, retrying");
        vTaskDelay(pdMS_TO_TICKS(10000));
    }

    while (true) {
        camera_fb_t *frame = camera_app_capture();
        if (!frame) {
            capture_failures++;
            if (capture_failures == 5) {
                ESP_LOGI(TAG, "camera capture failed repeatedly, reinitializing");
                esp_camera_deinit();
                while (camera_app_init() != ESP_OK) {
                    vTaskDelay(pdMS_TO_TICKS(10000));
                }
                capture_failures = 0;
            }
            vTaskDelay(pdMS_TO_TICKS(10000));
            continue;
        }

        capture_failures = 0;
        esp_err_t err = http_upload_jpeg(s_config.image_upload_url, frame->buf, frame->len);
        if (err == ESP_OK) {
            upload_failures = 0;
            ESP_LOGI(TAG, "image uploaded");
        } else if (err != ESP_ERR_INVALID_STATE && err != ESP_ERR_INVALID_ARG) {
            upload_failures++;
            if (upload_failures == 1 || upload_failures % 30 == 0) {
                ESP_LOGW(TAG, "image upload failed %d times: %s", upload_failures, esp_err_to_name(err));
            }
        }

        camera_app_return_frame(frame);
        vTaskDelay(pdMS_TO_TICKS(s_config.camera_upload_interval_ms));
    }
}

void app_main(void) {
    memset(&s_status, 0, sizeof(s_status));
    memset(&s_latest_sample, 0, sizeof(s_latest_sample));
    memset(&s_latest_fusion, 0, sizeof(s_latest_fusion));
    s_status.wifi = APP_STATUS_LINK_DISABLED;
    s_status.cloud = APP_STATUS_LINK_DISABLED;

    ESP_ERROR_CHECK(app_config_load(&s_config));
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(control_state_init());

    s_latest_mutex = xSemaphoreCreateMutex();
    s_command_queue = xQueueCreate(AIOT_COMMAND_QUEUE_LENGTH, sizeof(mqtt_app_command_t));
    if (!s_latest_mutex || !s_command_queue) {
        ESP_LOGE(TAG, "failed to create application mutex/queue");
        return;
    }

    err = sensors_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "sensor layer degraded: %s", esp_err_to_name(err));
    }
    s_status.last_sensor_result = err;
    err = voice_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "voice module degraded: %s", esp_err_to_name(err));
    }

    err = wifi_start();
    if (err == ESP_ERR_INVALID_STATE) {
        s_status.wifi = APP_STATUS_LINK_DISABLED;
    } else {
        s_status.wifi = link_status_from_result(err);
    }

    ESP_ERROR_CHECK(http_upload_init(&s_config));
    ESP_ERROR_CHECK(mqtt_app_set_command_handler(on_command));
    err = mqtt_app_init(&s_config);
    if (err == ESP_OK && s_config.wifi_enabled && s_config.mqtt_enabled) {
        err = mqtt_app_start();
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "MQTT start failed: %s", esp_err_to_name(err));
        }
    }
    s_status.cloud = s_config.mqtt_enabled ? link_status_from_result(err) : APP_STATUS_LINK_DISABLED;

    err = inputs_start();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "input task failed: %s", esp_err_to_name(err));
    }

    BaseType_t ok = xTaskCreate(telemetry_task, "telemetry", 8192, NULL, 5, NULL);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "failed to start telemetry task");
    }

    ok = xTaskCreate(actuator_task, "actuator_task", 4096, NULL, 4, NULL);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "failed to start actuator task");
    }

    if (CONFIG_APP_MQ2_ENABLED) {
        ok = xTaskCreate(safety_task, "smoke_safety", 4096, NULL, 6, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "failed to start smoke safety task");
        }
    }

    if (CONFIG_APP_DISPLAY_ENABLED) {
        ok = xTaskCreate(display_task, "display_task", 4096, NULL, 4, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "failed to start display task");
        }
    }

    if (CONFIG_APP_CAMERA_ENABLED) {
        ok = xTaskCreate(camera_upload_task, "camera_task", 4096, NULL, 2, NULL);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "failed to start camera task");
        }
    }

    ESP_LOGI(TAG, "AIoT firmware mainline started device_id=%s", s_config.device_id);
}
