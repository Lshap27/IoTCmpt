#include "control_state.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"

static control_state_t s_state;
static SemaphoreHandle_t s_mutex;
static TickType_t s_smoke_silenced_until;

#define CONTROL_NVS_NAMESPACE "control"
#define CONTROL_NVS_PRIORITY  "priority"

static void refresh_locked(void) {
    const bool smoke_active = (s_state.alarm_sources & CONTROL_ALARM_SMOKE) != 0;
    if (!smoke_active) {
        s_smoke_silenced_until = 0;
    }
    const bool silence_active =
        smoke_active && s_smoke_silenced_until != 0 && (int32_t)(s_smoke_silenced_until - xTaskGetTickCount()) > 0;
    if (!silence_active) {
        s_smoke_silenced_until = 0;
    }
    s_state.smoke_silenced = silence_active;
    const uint32_t effective = silence_active ? (s_state.alarm_sources & ~CONTROL_ALARM_SMOKE) : s_state.alarm_sources;
    s_state.alarm_on = effective != 0;
    s_state.manual_override = s_state.manual_window_override || s_state.manual_led_override;
}

esp_err_t control_state_init(void) {
    memset(&s_state, 0, sizeof(s_state));
    s_state.priority = CONTROL_PRIORITY_MANUAL_FIRST;
    nvs_handle_t handle;
    if (nvs_open(CONTROL_NVS_NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
        uint8_t stored = 0;
        if (nvs_get_u8(handle, CONTROL_NVS_PRIORITY, &stored) == ESP_OK && stored <= CONTROL_PRIORITY_AUTO_FIRST) {
            s_state.priority = (control_priority_t)stored;
        }
        nvs_close(handle);
    }
    s_mutex = xSemaphoreCreateMutex();
    return s_mutex ? ESP_OK : ESP_ERR_NO_MEM;
}

void control_state_get(control_state_t *out_state) {
    if (!out_state) {
        return;
    }

    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        refresh_locked();
        *out_state = s_state;
        xSemaphoreGive(s_mutex);
    } else {
        *out_state = s_state;
    }
}

void control_state_set_window_open(bool open) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.window_open = open;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.window_open = open;
    }
}

void control_state_set_alarm(bool on) {
    control_state_set_alarm_source(CONTROL_ALARM_COMMAND, on);
}

void control_state_set_alarm_source(control_alarm_source_t source, bool on) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        if (on) {
            s_state.alarm_sources |= (uint32_t)source;
        } else {
            s_state.alarm_sources &= ~((uint32_t)source);
        }
        refresh_locked();
        xSemaphoreGive(s_mutex);
    } else {
        if (on) {
            s_state.alarm_sources |= (uint32_t)source;
        } else {
            s_state.alarm_sources &= ~((uint32_t)source);
        }
        refresh_locked();
    }
}

void control_state_set_led(bool on) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.led_on = on;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.led_on = on;
    }
}

void control_state_set_manual_window(bool enabled, bool open) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.manual_window_override = enabled && s_state.priority == CONTROL_PRIORITY_MANUAL_FIRST;
        s_state.manual_open = open;
        refresh_locked();
        xSemaphoreGive(s_mutex);
    } else {
        s_state.manual_window_override = enabled && s_state.priority == CONTROL_PRIORITY_MANUAL_FIRST;
        s_state.manual_open = open;
        refresh_locked();
    }
}

void control_state_set_manual_led(bool enabled, bool on) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.manual_led_override = enabled && s_state.priority == CONTROL_PRIORITY_MANUAL_FIRST;
        s_state.manual_led_on = on;
        refresh_locked();
        xSemaphoreGive(s_mutex);
    }
}

void control_state_toggle_manual_window(void) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.manual_window_override = s_state.priority == CONTROL_PRIORITY_MANUAL_FIRST;
        s_state.manual_open = !s_state.manual_open;
        refresh_locked();
        xSemaphoreGive(s_mutex);
    } else {
        s_state.manual_window_override = s_state.priority == CONTROL_PRIORITY_MANUAL_FIRST;
        s_state.manual_open = !s_state.manual_open;
        refresh_locked();
    }
}

esp_err_t control_state_set_priority(control_priority_t priority) {
    if (priority != CONTROL_PRIORITY_MANUAL_FIRST && priority != CONTROL_PRIORITY_AUTO_FIRST) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    esp_err_t err = nvs_open(CONTROL_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_set_u8(handle, CONTROL_NVS_PRIORITY, (uint8_t)priority);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    if (err != ESP_OK) {
        return err;
    }
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.priority = priority;
        if (priority == CONTROL_PRIORITY_AUTO_FIRST) {
            s_state.manual_window_override = false;
            s_state.manual_led_override = false;
        }
        refresh_locked();
        xSemaphoreGive(s_mutex);
    }
    return ESP_OK;
}

void control_state_resume_auto(void) {
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        s_state.manual_window_override = false;
        s_state.manual_led_override = false;
        refresh_locked();
        xSemaphoreGive(s_mutex);
    }
}

bool control_state_is_automatic_source_allowed(bool led) {
    control_state_t state;
    control_state_get(&state);
    return state.priority == CONTROL_PRIORITY_AUTO_FIRST ||
           !(led ? state.manual_led_override : state.manual_window_override);
}

esp_err_t control_state_silence_smoke(uint32_t seconds) {
    if (seconds < 10 || seconds > 600) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_mutex && xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
        if ((s_state.alarm_sources & CONTROL_ALARM_SMOKE) == 0) {
            xSemaphoreGive(s_mutex);
            return ESP_ERR_INVALID_STATE;
        }
        s_smoke_silenced_until = xTaskGetTickCount() + pdMS_TO_TICKS(seconds * 1000U);
        refresh_locked();
        xSemaphoreGive(s_mutex);
        return ESP_OK;
    }
    return ESP_ERR_INVALID_STATE;
}

const char *control_priority_name(control_priority_t priority) {
    return priority == CONTROL_PRIORITY_AUTO_FIRST ? "auto_first" : "manual_first";
}
