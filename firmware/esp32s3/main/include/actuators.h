#pragma once

#include "commands.h"
#include "esp_err.h"
#include "fusion.h"

esp_err_t actuator_init(void);
esp_err_t actuator_apply(const cloud_command_t *command, const fusion_state_t *state);
