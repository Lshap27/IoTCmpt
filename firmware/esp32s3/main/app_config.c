#include "app_config.h"

#include <string.h>

#include "app_config_defaults.h"
#include "app_string.h"

static void copy_config_string(char *dest, size_t dest_size, const char *source)
{
    if (dest_size == 0) {
        return;
    }

    if (!source) {
        dest[0] = '\0';
        return;
    }

    app_string_copy(dest, dest_size, source);
}

esp_err_t app_config_load(app_config_t *out_config)
{
    if (!out_config) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_config, 0, sizeof(*out_config));

    copy_config_string(out_config->device_id, sizeof(out_config->device_id), CONFIG_APP_DEVICE_ID);

    out_config->wifi_enabled = CONFIG_APP_WIFI_ENABLED;
    copy_config_string(out_config->wifi_ssid, sizeof(out_config->wifi_ssid), CONFIG_APP_WIFI_SSID);
    copy_config_string(out_config->wifi_password, sizeof(out_config->wifi_password), CONFIG_APP_WIFI_PASSWORD);

    out_config->mqtt_enabled = CONFIG_APP_MQTT_ENABLED;
    copy_config_string(out_config->mqtt_broker_uri, sizeof(out_config->mqtt_broker_uri), CONFIG_APP_MQTT_BROKER_URI);

    out_config->sensor_mock_enabled = CONFIG_APP_SENSOR_MOCK_ENABLED;
    out_config->sensor_interval_ms = CONFIG_APP_SENSOR_INTERVAL_MS;
    if (out_config->sensor_interval_ms == 0) {
        out_config->sensor_interval_ms = 5000;
    }

    out_config->image_upload_enabled = CONFIG_APP_IMAGE_UPLOAD_ENABLED;
    copy_config_string(out_config->image_upload_url, sizeof(out_config->image_upload_url), CONFIG_APP_IMAGE_UPLOAD_URL);

    out_config->camera_enabled = CONFIG_APP_CAMERA_ENABLED;
    out_config->display_enabled = CONFIG_APP_DISPLAY_ENABLED;
    out_config->actuator_enabled = CONFIG_APP_ACTUATOR_ENABLED;
    out_config->button_enabled = CONFIG_APP_BUTTON_ENABLED;

    out_config->sht30_sda_gpio = CONFIG_APP_SHT30_SDA_GPIO;
    out_config->sht30_scl_gpio = CONFIG_APP_SHT30_SCL_GPIO;
    out_config->tvoc_uart_num = CONFIG_APP_TVOC_UART_NUM;
    out_config->tvoc_tx_gpio = CONFIG_APP_TVOC_TX_GPIO;
    out_config->tvoc_rx_gpio = CONFIG_APP_TVOC_RX_GPIO;
    out_config->lm393_do_gpio = CONFIG_APP_LM393_DO_GPIO;

    out_config->servo_gpio = CONFIG_APP_SERVO_GPIO;
    out_config->button_gpio = CONFIG_APP_BUTTON_GPIO;
    out_config->beep_gpio = CONFIG_APP_BEEP_GPIO;
    out_config->beep_active_low = CONFIG_APP_BEEP_ACTIVE_LOW;

    out_config->tft_mosi_gpio = CONFIG_APP_TFT_MOSI_GPIO;
    out_config->tft_sclk_gpio = CONFIG_APP_TFT_SCLK_GPIO;
    out_config->tft_cs_gpio = CONFIG_APP_TFT_CS_GPIO;
    out_config->tft_dc_gpio = CONFIG_APP_TFT_DC_GPIO;
    out_config->tft_rst_gpio = CONFIG_APP_TFT_RST_GPIO;
    out_config->tft_blk_gpio = CONFIG_APP_TFT_BLK_GPIO;

    out_config->camera_pwdn_gpio = CONFIG_APP_CAMERA_PWDN_GPIO;
    out_config->camera_siod_gpio = CONFIG_APP_CAMERA_SIOD_GPIO;
    out_config->camera_sioc_gpio = CONFIG_APP_CAMERA_SIOC_GPIO;
    out_config->camera_d0_gpio = CONFIG_APP_CAMERA_D0_GPIO;
    out_config->camera_d1_gpio = CONFIG_APP_CAMERA_D1_GPIO;
    out_config->camera_d2_gpio = CONFIG_APP_CAMERA_D2_GPIO;
    out_config->camera_d3_gpio = CONFIG_APP_CAMERA_D3_GPIO;
    out_config->camera_d4_gpio = CONFIG_APP_CAMERA_D4_GPIO;
    out_config->camera_d5_gpio = CONFIG_APP_CAMERA_D5_GPIO;
    out_config->camera_d6_gpio = CONFIG_APP_CAMERA_D6_GPIO;
    out_config->camera_d7_gpio = CONFIG_APP_CAMERA_D7_GPIO;
    out_config->camera_vsync_gpio = CONFIG_APP_CAMERA_VSYNC_GPIO;
    out_config->camera_href_gpio = CONFIG_APP_CAMERA_HREF_GPIO;
    out_config->camera_pclk_gpio = CONFIG_APP_CAMERA_PCLK_GPIO;

    return ESP_OK;
}
