#pragma once

#include <stdbool.h>

#include "esp_err.h"

typedef struct {
    bool manual_override;
    bool manual_open;
    bool window_open;
    bool alarm_on;
} control_state_t;

esp_err_t control_state_init(void);
void control_state_get(control_state_t *out_state);
void control_state_set_window_open(bool open);
void control_state_set_alarm(bool on);
void control_state_set_manual(bool enabled, bool open);
void control_state_toggle_manual_window(void);
