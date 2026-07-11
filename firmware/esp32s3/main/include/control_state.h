#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef enum {
    CONTROL_ALARM_FUSION = 1U << 0,
    CONTROL_ALARM_COMMAND = 1U << 1,
    CONTROL_ALARM_SMOKE = 1U << 2,
} control_alarm_source_t;

typedef struct {
    bool manual_override;
    bool manual_open;
    bool window_open;
    bool alarm_on;
    bool led_on;
    uint32_t alarm_sources;
} control_state_t;

esp_err_t control_state_init(void);
void control_state_get(control_state_t *out_state);
void control_state_set_window_open(bool open);
void control_state_set_alarm(bool on);
void control_state_set_alarm_source(control_alarm_source_t source, bool on);
void control_state_set_led(bool on);
void control_state_set_manual(bool enabled, bool open);
void control_state_toggle_manual_window(void);
