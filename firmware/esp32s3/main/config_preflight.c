#include "config_preflight.h"

#include <stdbool.h>
#include <stddef.h>

#include "app_config_defaults.h"
#include "esp_log.h"

static const char *TAG = "PIN_PREFLIGHT";

typedef struct {
    const char *name;
    int gpio;
} pin_use_t;

esp_err_t config_preflight_validate(void) {
    pin_use_t pins[40];
    size_t count = 0;

#define ADD_PIN(label, value)                                                                                          \
    do {                                                                                                               \
        pins[count++] = (pin_use_t){.name = label, .gpio = value};                                                     \
    } while (0)

    if (!CONFIG_APP_SENSOR_MOCK_ENABLED) {
        ADD_PIN("SHT30 SDA", CONFIG_APP_SHT30_SDA_GPIO);
        ADD_PIN("SHT30 SCL", CONFIG_APP_SHT30_SCL_GPIO);
        ADD_PIN("TVOC TX", CONFIG_APP_TVOC_TX_GPIO);
        ADD_PIN("TVOC RX", CONFIG_APP_TVOC_RX_GPIO);
        ADD_PIN("LM393 DO", CONFIG_APP_LM393_DO_GPIO);
    }
    if (CONFIG_APP_MQ2_ENABLED)
        ADD_PIN("MQ2 DO", CONFIG_APP_MQ2_DO_GPIO);
    if (CONFIG_APP_VOICE_ENABLED)
        ADD_PIN("SYN6288 BY", CONFIG_APP_SYN6288_BY_GPIO);
    if (CONFIG_APP_ACTUATOR_ENABLED) {
        ADD_PIN("SERVO", CONFIG_APP_SERVO_GPIO);
        ADD_PIN("BEEP", CONFIG_APP_BEEP_GPIO);
    }
    if (CONFIG_APP_LED_ENABLED)
        ADD_PIN("LED", CONFIG_APP_LED_GPIO);
    if (CONFIG_APP_BUTTON_ENABLED)
        ADD_PIN("BUTTON", CONFIG_APP_BUTTON_GPIO);
    if (CONFIG_APP_DISPLAY_ENABLED) {
        ADD_PIN("TFT MOSI", CONFIG_APP_TFT_MOSI_GPIO);
        ADD_PIN("TFT SCLK", CONFIG_APP_TFT_SCLK_GPIO);
        ADD_PIN("TFT CS", CONFIG_APP_TFT_CS_GPIO);
        ADD_PIN("TFT DC", CONFIG_APP_TFT_DC_GPIO);
        ADD_PIN("TFT RST", CONFIG_APP_TFT_RST_GPIO);
        ADD_PIN("TFT BLK", CONFIG_APP_TFT_BLK_GPIO);
    }
    if (CONFIG_APP_CAMERA_ENABLED) {
        ADD_PIN("CAM PWDN", CONFIG_APP_CAMERA_PWDN_GPIO);
        ADD_PIN("CAM SIOD", CONFIG_APP_CAMERA_SIOD_GPIO);
        ADD_PIN("CAM SIOC", CONFIG_APP_CAMERA_SIOC_GPIO);
        ADD_PIN("CAM D0", CONFIG_APP_CAMERA_D0_GPIO);
        ADD_PIN("CAM D1", CONFIG_APP_CAMERA_D1_GPIO);
        ADD_PIN("CAM D2", CONFIG_APP_CAMERA_D2_GPIO);
        ADD_PIN("CAM D3", CONFIG_APP_CAMERA_D3_GPIO);
        ADD_PIN("CAM D4", CONFIG_APP_CAMERA_D4_GPIO);
        ADD_PIN("CAM D5", CONFIG_APP_CAMERA_D5_GPIO);
        ADD_PIN("CAM D6", CONFIG_APP_CAMERA_D6_GPIO);
        ADD_PIN("CAM D7", CONFIG_APP_CAMERA_D7_GPIO);
        ADD_PIN("CAM VSYNC", CONFIG_APP_CAMERA_VSYNC_GPIO);
        ADD_PIN("CAM HREF", CONFIG_APP_CAMERA_HREF_GPIO);
        ADD_PIN("CAM PCLK", CONFIG_APP_CAMERA_PCLK_GPIO);
    }
#undef ADD_PIN

    bool invalid = false;
    for (size_t i = 0; i < count; ++i) {
        if (pins[i].gpio < 0 || pins[i].gpio > 48) {
            ESP_LOGE(TAG, "%s uses invalid GPIO%d", pins[i].name, pins[i].gpio);
            invalid = true;
        }
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
        if (pins[i].gpio == 19 || pins[i].gpio == 20) {
            ESP_LOGE(TAG, "%s conflicts with native USB Serial/JTAG on GPIO%d", pins[i].name, pins[i].gpio);
            invalid = true;
        }
#endif
#if CONFIG_SPIRAM_MODE_OCT
        if (pins[i].gpio >= 35 && pins[i].gpio <= 37) {
            ESP_LOGE(TAG, "%s conflicts with octal PSRAM on GPIO%d", pins[i].name, pins[i].gpio);
            invalid = true;
        }
#endif
        for (size_t j = i + 1; j < count; ++j) {
            if (pins[i].gpio == pins[j].gpio) {
                ESP_LOGE(TAG, "GPIO%d is assigned to both %s and %s", pins[i].gpio, pins[i].name, pins[j].name);
                invalid = true;
            }
        }
    }
    if (invalid) {
        ESP_LOGE(TAG, "hardware configuration rejected; fix pin conflicts before startup");
        return ESP_ERR_INVALID_STATE;
    }
    ESP_LOGI(TAG, "hardware pin preflight passed (%u active pins)", (unsigned)count);
    return ESP_OK;
}
