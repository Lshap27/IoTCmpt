#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t voice_init(void);
void voice_update(bool smoke_detected, bool air_bad);
