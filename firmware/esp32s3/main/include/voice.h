#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t voice_init(void);
esp_err_t voice_speak_base64(const char *encoded);
