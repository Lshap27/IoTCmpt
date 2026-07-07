#pragma once

#include "esp_camera.h"
#include "esp_err.h"

esp_err_t camera_app_init(void);
camera_fb_t *camera_app_capture(void);
void camera_app_return_frame(camera_fb_t *frame);
