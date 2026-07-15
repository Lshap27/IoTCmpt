#pragma once

#include <stdbool.h>

#include "esp_err.h"

typedef enum {
    VOICE_ANNOUNCEMENT_SMOKE,
    VOICE_ANNOUNCEMENT_AIR_VENTILATION,
} voice_announcement_t;

esp_err_t voice_init(void);
esp_err_t voice_speak_base64(const char *encoded);
esp_err_t voice_announce(voice_announcement_t announcement);
void voice_set_smoke_state(bool active, bool silenced);
