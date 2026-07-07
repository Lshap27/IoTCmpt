#pragma once

#include <stddef.h>
#include <stdint.h>

#include "app_config.h"
#include "esp_err.h"

esp_err_t http_upload_init(const app_config_t *config);
esp_err_t http_upload_jpeg(const char *url, const uint8_t *data, size_t len);
