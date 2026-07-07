#include "sensors.h"

#include <string.h>

#include "app_config_defaults.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "SENSORS";

#define SHT30_ADDR         0x44
#define SHT30_CMD          0x2400
#define SHT30_I2C_DELAY_US 5

#define TVOC_BAUDRATE  9600
#define TVOC_BUF_SIZE  128
#define TVOC_FRAME_LEN 9
#define TVOC_HEADER_0  0x2C
#define TVOC_HEADER_1  0xE4

static uint32_t s_mock_counter;

static int sda_gpio(void) {
    return CONFIG_APP_SHT30_SDA_GPIO;
}

static int scl_gpio(void) {
    return CONFIG_APP_SHT30_SCL_GPIO;
}

static uart_port_t tvoc_uart(void) {
    return (uart_port_t)CONFIG_APP_TVOC_UART_NUM;
}

static void sht30_sda_out(void) {
    gpio_set_direction(sda_gpio(), GPIO_MODE_OUTPUT_OD);
}

static void sht30_sda_in(void) {
    gpio_set_direction(sda_gpio(), GPIO_MODE_INPUT);
}

static void sht30_scl_low(void) {
    gpio_set_level(scl_gpio(), 0);
}

static void sht30_scl_high(void) {
    gpio_set_level(scl_gpio(), 1);
}

static void sht30_sda_low(void) {
    gpio_set_level(sda_gpio(), 0);
}

static void sht30_sda_high(void) {
    gpio_set_level(sda_gpio(), 1);
}

static int sht30_sda_read(void) {
    return gpio_get_level(sda_gpio());
}

static void sht30_i2c_start(void) {
    sht30_sda_out();
    sht30_sda_high();
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US);
    sht30_sda_low();
    esp_rom_delay_us(SHT30_I2C_DELAY_US);
    sht30_scl_low();
}

static void sht30_i2c_stop(void) {
    sht30_sda_out();
    sht30_sda_low();
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US);
    sht30_sda_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US);
}

static bool sht30_i2c_write_byte(uint8_t byte) {
    sht30_sda_out();
    for (int i = 7; i >= 0; i--) {
        if (byte & (1 << i)) {
            sht30_sda_high();
        } else {
            sht30_sda_low();
        }
        esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
        sht30_scl_high();
        esp_rom_delay_us(SHT30_I2C_DELAY_US);
        sht30_scl_low();
        esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    }

    sht30_sda_in();
    sht30_sda_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    const bool ack = (sht30_sda_read() == 0);
    esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    sht30_scl_low();
    sht30_sda_out();
    return ack;
}

static uint8_t sht30_i2c_read_byte(bool send_ack) {
    uint8_t byte = 0;
    sht30_sda_in();
    sht30_sda_high();

    for (int i = 7; i >= 0; i--) {
        esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
        sht30_scl_high();
        esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
        if (sht30_sda_read()) {
            byte |= (1 << i);
        }
        sht30_scl_low();
    }

    sht30_sda_out();
    if (send_ack) {
        sht30_sda_low();
    } else {
        sht30_sda_high();
    }
    esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY_US);
    sht30_scl_low();
    esp_rom_delay_us(SHT30_I2C_DELAY_US / 2);
    sht30_sda_in();
    return byte;
}

static void sht30_init(void) {
    gpio_config_t io_cfg = {
        .pin_bit_mask = (1ULL << sda_gpio()) | (1ULL << scl_gpio()),
        .mode = GPIO_MODE_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_cfg);
    gpio_set_level(sda_gpio(), 1);
    gpio_set_level(scl_gpio(), 1);
    ESP_LOGI(TAG, "SHT30 软件 I2C 初始化完成（SCL=GPIO%d SDA=GPIO%d）", scl_gpio(), sda_gpio());
}

static bool sht30_read(float *temp, float *hum) {
    sht30_i2c_start();
    if (!sht30_i2c_write_byte((SHT30_ADDR << 1) | 0)) {
        sht30_i2c_stop();
        ESP_LOGW(TAG, "SHT30 写地址 ACK 失败");
        return false;
    }

    sht30_i2c_write_byte((SHT30_CMD >> 8) & 0xFF);
    sht30_i2c_write_byte(SHT30_CMD & 0xFF);
    sht30_i2c_stop();
    vTaskDelay(pdMS_TO_TICKS(30));

    sht30_i2c_start();
    if (!sht30_i2c_write_byte((SHT30_ADDR << 1) | 1)) {
        sht30_i2c_stop();
        ESP_LOGW(TAG, "SHT30 读地址 ACK 失败");
        return false;
    }

    uint8_t data[6];
    for (int i = 0; i < 6; i++) {
        data[i] = sht30_i2c_read_byte(i < 5);
    }
    sht30_i2c_stop();

    const uint16_t raw_temp = (data[0] << 8) | data[1];
    const uint16_t raw_hum = (data[3] << 8) | data[4];
    *temp = -45.0f + 175.0f * ((float)raw_temp / 65535.0f);
    *hum = 100.0f * ((float)raw_hum / 65535.0f);
    return true;
}

static void tvoc_init(void) {
    gpio_config_t rx_pullup = {
        .pin_bit_mask = 1ULL << CONFIG_APP_TVOC_RX_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&rx_pullup);

    uart_config_t uart_config = {
        .baud_rate = TVOC_BAUDRATE,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(tvoc_uart(), TVOC_BUF_SIZE * 2, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(tvoc_uart(), &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(tvoc_uart(), CONFIG_APP_TVOC_TX_GPIO, CONFIG_APP_TVOC_RX_GPIO, UART_PIN_NO_CHANGE,
                                 UART_PIN_NO_CHANGE));
    ESP_LOGI(TAG, "TVOC301 UART%d 初始化完成", CONFIG_APP_TVOC_UART_NUM);
}

static bool tvoc_read(uint16_t *tvoc, uint16_t *hcho, uint16_t *eco2) {
    uint8_t data[64];
    uart_flush_input(tvoc_uart());
    const int len = uart_read_bytes(tvoc_uart(), data, sizeof(data), pdMS_TO_TICKS(1000));

    for (int i = 0; i <= len - TVOC_FRAME_LEN; i++) {
        if (data[i] != TVOC_HEADER_0 || data[i + 1] != TVOC_HEADER_1) {
            continue;
        }

        uint8_t sum = 0;
        for (int j = 0; j < TVOC_FRAME_LEN - 1; j++) {
            sum += data[i + j];
        }

        if (sum == data[i + TVOC_FRAME_LEN - 1]) {
            *tvoc = (data[i + 2] << 8) | data[i + 3];
            *hcho = (data[i + 4] << 8) | data[i + 5];
            *eco2 = (data[i + 6] << 8) | data[i + 7];
            return true;
        }
    }

    return false;
}

static void lm393_init(void) {
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << CONFIG_APP_LM393_DO_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
    ESP_LOGI(TAG, "LM393 GPIO%d 初始化完成", CONFIG_APP_LM393_DO_GPIO);
}

esp_err_t sensors_init(void) {
    if (CONFIG_APP_SENSOR_MOCK_ENABLED) {
        ESP_LOGW(TAG, "当前使用模拟传感器数据");
        return ESP_OK;
    }

    sht30_init();
    tvoc_init();
    lm393_init();
    vTaskDelay(pdMS_TO_TICKS(1000));
    return ESP_OK;
}

esp_err_t sensors_read(sensor_sample_t *out_sample) {
    if (!out_sample) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_sample, 0, sizeof(*out_sample));
    out_sample->timestamp_ms = esp_timer_get_time() / 1000;

    if (CONFIG_APP_SENSOR_MOCK_ENABLED) {
        const uint32_t step = s_mock_counter++;
        out_sample->temperature_c = 24.0f + (float)(step % 6) * 0.4f;
        out_sample->humidity_percent = 48.0f + (float)(step % 5) * 1.5f;
        out_sample->climate_valid = true;
        out_sample->tvoc_ppb = 180 + (uint16_t)((step % 8) * 35);
        out_sample->hcho_ug_m3 = 20 + (uint16_t)((step % 4) * 5);
        out_sample->eco2_ppm = 520 + (uint16_t)((step % 7) * 80);
        out_sample->air_valid = true;
        out_sample->light_is_dark = (step % 4) == 0;
        out_sample->light_valid = true;
        return ESP_OK;
    }

    float temp = 0.0f;
    float hum = 0.0f;
    out_sample->climate_valid = sht30_read(&temp, &hum);
    if (out_sample->climate_valid) {
        out_sample->temperature_c = temp;
        out_sample->humidity_percent = hum;
    }

    uint16_t tvoc = 0;
    uint16_t hcho = 0;
    uint16_t eco2 = 0;
    out_sample->air_valid = tvoc_read(&tvoc, &hcho, &eco2);
    if (out_sample->air_valid) {
        out_sample->tvoc_ppb = tvoc;
        out_sample->hcho_ug_m3 = hcho;
        out_sample->eco2_ppm = eco2;
    }

    out_sample->light_is_dark = gpio_get_level(CONFIG_APP_LM393_DO_GPIO) == 0;
    out_sample->light_valid = true;

    if (!out_sample->climate_valid && !out_sample->air_valid && !out_sample->light_valid) {
        return ESP_ERR_NOT_FOUND;
    }

    return ESP_OK;
}
