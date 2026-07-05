#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "app_config_defaults.h"
#include "esp_err.h"

#define APP_CONFIG_WIFI_SSID_MAX_LEN 32
#define APP_CONFIG_WIFI_PASSWORD_MAX_LEN 64
#define APP_CONFIG_CLOUD_ENDPOINT_MAX_LEN 256
#define APP_CONFIG_CLOUD_MODEL_MAX_LEN 64
#define APP_CONFIG_CLOUD_TOKEN_MAX_LEN 256
#define APP_CONFIG_BACKEND_URL_MAX_LEN 256

typedef struct {
    bool wifi_enabled;
    char wifi_ssid[APP_CONFIG_WIFI_SSID_MAX_LEN + 1];
    char wifi_password[APP_CONFIG_WIFI_PASSWORD_MAX_LEN + 1];

    bool cloud_enabled;
    char cloud_endpoint[APP_CONFIG_CLOUD_ENDPOINT_MAX_LEN + 1];
    char cloud_model[APP_CONFIG_CLOUD_MODEL_MAX_LEN + 1];
    char cloud_token[APP_CONFIG_CLOUD_TOKEN_MAX_LEN + 1];

    bool sensor_mock_enabled;
    uint32_t sensor_interval_ms;

    bool backend_enabled;
    char sensor_upload_url[APP_CONFIG_BACKEND_URL_MAX_LEN + 1];
    char image_upload_url[APP_CONFIG_BACKEND_URL_MAX_LEN + 1];
    char pose_upload_url[APP_CONFIG_BACKEND_URL_MAX_LEN + 1];

    bool camera_enabled;
    bool display_enabled;
    bool actuator_enabled;
    bool button_enabled;

    int sht30_sda_gpio;
    int sht30_scl_gpio;
    int tvoc_uart_num;
    int tvoc_tx_gpio;
    int tvoc_rx_gpio;
    int lm393_do_gpio;

    int servo_gpio;
    int button_gpio;
    int beep_gpio;
    bool beep_active_low;

    int tft_mosi_gpio;
    int tft_sclk_gpio;
    int tft_cs_gpio;
    int tft_dc_gpio;
    int tft_rst_gpio;
    int tft_blk_gpio;

    int camera_xclk_gpio;
    int camera_siod_gpio;
    int camera_sioc_gpio;
    int camera_d0_gpio;
    int camera_d1_gpio;
    int camera_d2_gpio;
    int camera_d3_gpio;
    int camera_d4_gpio;
    int camera_d5_gpio;
    int camera_d6_gpio;
    int camera_d7_gpio;
    int camera_vsync_gpio;
    int camera_href_gpio;
    int camera_pclk_gpio;
} app_config_t;

esp_err_t app_config_load(app_config_t *out_config);
