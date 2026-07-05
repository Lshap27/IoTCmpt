#include "control_state.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static control_state_t s_state;
static SemaphoreHandle_t s_mutex;

esp_err_t control_state_init(void)
{
    memset(&s_state, 0, sizeof(s_state));
    s_mutex = xSemaphoreCreateMutex();
    return s_mutex ? ESP_OK : ESP_ERR_NO_MEM;
}

void control_state_get(control_state_t *out_state)
{
    if (!out_state) {
        return;
    }

    if (s_mutex && xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        *out_state = s_state;
        xSemaphoreGive(s_mutex);
    } else {
        *out_state = s_state;
    }
}

void control_state_set_window_open(bool open)
{
    if (s_mutex && xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_state.window_open = open;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.window_open = open;
    }
}

void control_state_set_alarm(bool on)
{
    if (s_mutex && xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_state.alarm_on = on;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.alarm_on = on;
    }
}

void control_state_set_manual(bool enabled, bool open)
{
    if (s_mutex && xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_state.manual_override = enabled;
        s_state.manual_open = open;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.manual_override = enabled;
        s_state.manual_open = open;
    }
}

void control_state_toggle_manual_window(void)
{
    if (s_mutex && xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_state.manual_override = true;
        s_state.manual_open = !s_state.manual_open;
        s_state.alarm_on = false;
        xSemaphoreGive(s_mutex);
    } else {
        s_state.manual_override = true;
        s_state.manual_open = !s_state.manual_open;
        s_state.alarm_on = false;
    }
}
