#ifndef SENSOR_UPLOAD_H
#define SENSOR_UPLOAD_H

#include "esp_err.h"

// 传感器数据结构（与主程序保持一致）
typedef struct {
    float   temperature;
    float   humidity;
    bool    sht30_valid;
    uint16_t tvoc;
    uint16_t hcho;
    uint16_t eco2;
    bool    tvoc_valid;
    int     light_dark;
    bool    light_valid;
    bool    need_open_window;
    bool    manual_override;
    bool    manual_open;
    bool    beep_alarm;
} sensor_data_t;

// 上传传感器数据到后端
esp_err_t upload_sensor_data(const sensor_data_t *data);

#endif