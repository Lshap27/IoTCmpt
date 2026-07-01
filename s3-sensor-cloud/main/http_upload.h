#pragma once

#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t http_upload_jpeg(const char *url, const uint8_t *jpeg_data, size_t jpeg_len);