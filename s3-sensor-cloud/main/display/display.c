#include "display.h"

#include <string.h>

#include "control_state.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "DISPLAY";

#define TFT_SPI_HOST SPI2_HOST
#define TFT_W 128
#define TFT_H 128

#define ST7735_SWRESET 0x01
#define ST7735_SLPOUT 0x11
#define ST7735_NORON 0x13
#define ST7735_INVON 0x21
#define ST7735_DISPON 0x29
#define ST7735_CASET 0x2A
#define ST7735_RASET 0x2B
#define ST7735_RAMWR 0x2C
#define ST7735_MADCTL 0x36
#define ST7735_COLMOD 0x3A

#define RGB565(r, g, b) ((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3))
#define COLOR_BLACK RGB565(0, 0, 0)
#define COLOR_GREEN RGB565(40, 220, 80)
#define COLOR_YELLOW RGB565(250, 210, 40)
#define COLOR_RED RGB565(240, 50, 50)
#define COLOR_BLUE RGB565(40, 120, 240)
#define COLOR_CYAN RGB565(40, 210, 210)
#define COLOR_GRAY RGB565(90, 90, 110)
#define COLOR_DARK RGB565(8, 10, 18)
#define COLOR_PANEL RGB565(24, 28, 42)

static spi_device_handle_t s_tft_spi;
static uint16_t s_fb[TFT_H][TFT_W];

static void tft_cs(int level)
{
    gpio_set_level(CONFIG_APP_TFT_CS_GPIO, level);
}

static void tft_dc(int level)
{
    gpio_set_level(CONFIG_APP_TFT_DC_GPIO, level);
}

static void tft_spi_send(const uint8_t *data, size_t len)
{
    spi_transaction_t transaction = {
        .length = len * 8,
        .tx_buffer = data,
    };
    spi_device_transmit(s_tft_spi, &transaction);
}

static void tft_cmd(uint8_t cmd)
{
    tft_dc(0);
    tft_cs(0);
    tft_spi_send(&cmd, 1);
    tft_cs(1);
}

static void tft_data(const uint8_t *data, size_t len)
{
    tft_dc(1);
    tft_cs(0);
    tft_spi_send(data, len);
    tft_cs(1);
}

static void fb_fill(uint16_t color)
{
    for (int y = 0; y < TFT_H; y++) {
        for (int x = 0; x < TFT_W; x++) {
            s_fb[y][x] = color;
        }
    }
}

static void fb_rect(int x, int y, int w, int h, uint16_t color)
{
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > TFT_W) {
        w = TFT_W - x;
    }
    if (y + h > TFT_H) {
        h = TFT_H - y;
    }
    if (w <= 0 || h <= 0) {
        return;
    }

    for (int row = y; row < y + h; row++) {
        for (int col = x; col < x + w; col++) {
            s_fb[row][col] = color;
        }
    }
}

static int clamp_int(int value, int min, int max)
{
    if (value < min) {
        return min;
    }
    if (value > max) {
        return max;
    }
    return value;
}

static void draw_bar(int y, int value, int max_value, uint16_t color)
{
    fb_rect(8, y, 112, 9, COLOR_PANEL);
    const int width = clamp_int(value * 112 / max_value, 0, 112);
    fb_rect(8, y, width, 9, color);
}

static void tft_flush(void)
{
    uint8_t data[4];
    data[0] = 0x00;
    data[1] = 0x02;
    data[2] = 0x00;
    data[3] = 0x81;
    tft_cmd(ST7735_CASET);
    tft_data(data, 4);

    data[0] = 0x00;
    data[1] = 0x01;
    data[2] = 0x00;
    data[3] = 0x80;
    tft_cmd(ST7735_RASET);
    tft_data(data, 4);

    tft_cmd(ST7735_RAMWR);
    tft_dc(1);
    tft_cs(0);
    tft_spi_send((const uint8_t *)s_fb, TFT_W * TFT_H * 2);
    tft_cs(1);
}

esp_err_t display_init(void)
{
    if (!CONFIG_APP_DISPLAY_ENABLED) {
        return ESP_ERR_INVALID_STATE;
    }

    if (CONFIG_APP_CAMERA_ENABLED && CONFIG_APP_TFT_CS_GPIO == CONFIG_APP_CAMERA_XCLK_GPIO) {
        ESP_LOGW(TAG, "TFT CS GPIO%d conflicts with camera XCLK", CONFIG_APP_TFT_CS_GPIO);
    }

    gpio_config_t io = {
        .pin_bit_mask = (1ULL << CONFIG_APP_TFT_CS_GPIO) | (1ULL << CONFIG_APP_TFT_DC_GPIO) |
                        (1ULL << CONFIG_APP_TFT_RST_GPIO) | (1ULL << CONFIG_APP_TFT_BLK_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    gpio_set_level(CONFIG_APP_TFT_BLK_GPIO, 1);
    gpio_set_level(CONFIG_APP_TFT_CS_GPIO, 1);
    gpio_set_level(CONFIG_APP_TFT_RST_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(5));
    gpio_set_level(CONFIG_APP_TFT_RST_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(CONFIG_APP_TFT_RST_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(150));

    spi_bus_config_t bus = {
        .mosi_io_num = CONFIG_APP_TFT_MOSI_GPIO,
        .miso_io_num = -1,
        .sclk_io_num = CONFIG_APP_TFT_SCLK_GPIO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = TFT_W * TFT_H * 2,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(TFT_SPI_HOST, &bus, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t dev = {
        .clock_speed_hz = 2000000,
        .mode = 0,
        .spics_io_num = -1,
        .queue_size = 1,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(TFT_SPI_HOST, &dev, &s_tft_spi));

    tft_cmd(ST7735_SWRESET);
    vTaskDelay(pdMS_TO_TICKS(150));
    tft_cmd(ST7735_SLPOUT);
    vTaskDelay(pdMS_TO_TICKS(120));
    uint8_t colmod[] = {0x05};
    tft_cmd(ST7735_COLMOD);
    tft_data(colmod, sizeof(colmod));
    uint8_t madctl[] = {0xC0};
    tft_cmd(ST7735_MADCTL);
    tft_data(madctl, sizeof(madctl));
    tft_cmd(ST7735_INVON);
    tft_cmd(ST7735_NORON);
    vTaskDelay(pdMS_TO_TICKS(10));
    tft_cmd(ST7735_DISPON);
    vTaskDelay(pdMS_TO_TICKS(100));

    fb_fill(COLOR_DARK);
    tft_flush();
    ESP_LOGI(TAG, "Display init OK");
    return ESP_OK;
}

esp_err_t display_render(const sensor_sample_t *sample, const fusion_state_t *state, const app_status_t *status)
{
    if (!CONFIG_APP_DISPLAY_ENABLED) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!sample || !state || !status) {
        return ESP_ERR_INVALID_ARG;
    }

    control_state_t control;
    control_state_get(&control);

    uint16_t status_color = COLOR_GRAY;
    if (state->air_quality == FUSION_AIR_QUALITY_GOOD) {
        status_color = COLOR_GREEN;
    } else if (state->air_quality == FUSION_AIR_QUALITY_WATCH) {
        status_color = COLOR_YELLOW;
    } else if (state->air_quality == FUSION_AIR_QUALITY_ALERT) {
        status_color = COLOR_RED;
    }

    fb_fill(COLOR_DARK);
    fb_rect(0, 0, TFT_W, 18, status_color);
    draw_bar(24, sample->climate_valid ? (int)(sample->temperature_c * 3.0f) : 0, 120, COLOR_RED);
    draw_bar(38, sample->climate_valid ? (int)sample->humidity_percent : 0, 100, COLOR_CYAN);
    draw_bar(52, sample->air_valid ? sample->tvoc_ppb : 0, 800, COLOR_YELLOW);
    draw_bar(66, sample->air_valid ? sample->eco2_ppm : 0, 2000, COLOR_BLUE);
    draw_bar(80, sample->air_valid ? sample->hcho_ug_m3 : 0, 140, COLOR_RED);

    fb_rect(8, 99, control.window_open ? 52 : 20, 12, control.window_open ? COLOR_GREEN : COLOR_GRAY);
    fb_rect(68, 99, control.manual_override ? 52 : 20, 12, control.manual_override ? COLOR_YELLOW : COLOR_GRAY);
    fb_rect(8, 116, control.alarm_on ? 112 : 20, 7, control.alarm_on ? COLOR_RED : COLOR_GRAY);

    tft_flush();
    return ESP_OK;
}
