#include "display.h"

#include <stdio.h>
#include <string.h>

#include "app_config_defaults.h"
#include "control_state.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "DISPLAY";

#define TFT_SPI_HOST SPI2_HOST
#define TFT_W        128
#define TFT_H        128

#define ST7735_SWRESET 0x01
#define ST7735_SLPOUT  0x11
#define ST7735_NORON   0x13
#define ST7735_INVON   0x21
#define ST7735_DISPON  0x29
#define ST7735_CASET   0x2A
#define ST7735_RASET   0x2B
#define ST7735_RAMWR   0x2C
#define ST7735_MADCTL  0x36
#define ST7735_COLMOD  0x3A

/* 帧缓冲以 SPI 发送字节序（高字节在前）存储像素：tft_flush 直接把 s_fb 的内存字节
 * 发给 ST7735，而 ESP32-S3 是小端，因此这里预先交换 RGB565 的高低字节。 */
#define RGB565_RAW(r, g, b) ((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3))
#define RGB565(r, g, b) \
    ((uint16_t)(((RGB565_RAW(r, g, b) & 0xFF) << 8) | ((RGB565_RAW(r, g, b) >> 8) & 0xFF)))
#define COLOR_BLACK     RGB565(0, 0, 0)
#define COLOR_GREEN     RGB565(40, 220, 80)
#define COLOR_YELLOW    RGB565(250, 210, 40)
#define COLOR_RED       RGB565(240, 50, 50)
#define COLOR_BLUE      RGB565(40, 120, 240)
#define COLOR_CYAN      RGB565(40, 210, 210)
#define COLOR_WHITE     RGB565(235, 238, 245)
#define COLOR_GRAY      RGB565(90, 90, 110)
#define COLOR_DARK      RGB565(8, 10, 18)
#define COLOR_PANEL     RGB565(24, 28, 42)

static spi_device_handle_t s_tft_spi;
static uint16_t s_fb[TFT_H][TFT_W];

static void tft_cs(int level) {
    gpio_set_level(CONFIG_APP_TFT_CS_GPIO, level);
}

static void tft_dc(int level) {
    gpio_set_level(CONFIG_APP_TFT_DC_GPIO, level);
}

static void tft_spi_send(const uint8_t *data, size_t len) {
    spi_transaction_t transaction = {
        .length = len * 8,
        .tx_buffer = data,
    };
    spi_device_transmit(s_tft_spi, &transaction);
}

static void tft_cmd(uint8_t cmd) {
    tft_dc(0);
    tft_cs(0);
    tft_spi_send(&cmd, 1);
    tft_cs(1);
}

static void tft_data(const uint8_t *data, size_t len) {
    tft_dc(1);
    tft_cs(0);
    tft_spi_send(data, len);
    tft_cs(1);
}

static void fb_fill(uint16_t color) {
    for (int y = 0; y < TFT_H; y++) {
        for (int x = 0; x < TFT_W; x++) {
            s_fb[y][x] = color;
        }
    }
}

static void fb_rect(int x, int y, int w, int h, uint16_t color) {
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

static const char *font3x5(char ch) {
    switch (ch) {
    case 'A':
        return "010101111101101";
    case 'B':
        return "110101110101110";
    case 'C':
        return "011100100100011";
    case 'D':
        return "110101101101110";
    case 'E':
        return "111100110100111";
    case 'F':
        return "111100110100100";
    case 'G':
        return "011100101101011";
    case 'H':
        return "101101111101101";
    case 'I':
        return "111010010010111";
    case 'J':
        return "001001001101010";
    case 'K':
        return "101101110101101";
    case 'L':
        return "100100100100111";
    case 'M':
        return "101111111101101";
    case 'N':
        return "101111111111101";
    case 'O':
        return "010101101101010";
    case 'P':
        return "110101110100100";
    case 'Q':
        return "010101101111011";
    case 'R':
        return "110101110101101";
    case 'S':
        return "011100010001110";
    case 'T':
        return "111010010010010";
    case 'U':
        return "101101101101111";
    case 'V':
        return "101101101101010";
    case 'W':
        return "101101111111101";
    case 'X':
        return "101101010101101";
    case 'Y':
        return "101101010010010";
    case 'Z':
        return "111001010100111";
    case '0':
        return "111101101101111";
    case '1':
        return "010110010010111";
    case '2':
        return "110001111100111";
    case '3':
        return "110001111001110";
    case '4':
        return "101101111001001";
    case '5':
        return "111100110001110";
    case '6':
        return "111100111101111";
    case '7':
        return "111001010010010";
    case '8':
        return "111101111101111";
    case '9':
        return "111101111001111";
    case ':':
        return "000010000010000";
    case '.':
        return "000000000000010";
    case '-':
        return "000000111000000";
    case '%':
        return "101001010100101";
    case '?':
        return "110001010000010";
    default:
        return "000000000000000";
    }
}

static void draw_text(int x, int y, const char *text, uint16_t color) {
    while (*text && x + 3 <= TFT_W) {
        const char *glyph = font3x5(*text++);
        for (int row = 0; row < 5; row++) {
            for (int col = 0; col < 3; col++) {
                if (glyph[row * 3 + col] == '1') {
                    fb_rect(x + col, y + row, 1, 1, color);
                }
            }
        }
        x += 4;
    }
}

static void tft_flush(void) {
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

esp_err_t display_init(void) {
    if (!CONFIG_APP_DISPLAY_ENABLED) {
        return ESP_ERR_INVALID_STATE;
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
    ESP_LOGI(TAG, "显示屏初始化完成");
    return ESP_OK;
}

esp_err_t display_render(const sensor_sample_t *sample, const fusion_state_t *state, const app_status_t *status) {
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

    const char *air = state->air_quality == FUSION_AIR_QUALITY_GOOD    ? "GOOD"
                      : state->air_quality == FUSION_AIR_QUALITY_WATCH ? "WATCH"
                      : state->air_quality == FUSION_AIR_QUALITY_ALERT ? "ALERT"
                                                                       : "UNKNOWN";
    const char *light = !sample->light_valid ? "NA" : (sample->light_is_dark ? "DARK" : "LIGHT");
    const char *smoke = !sample->smoke_valid ? "NA" : (sample->smoke_detected ? "YES" : "NO");
    char line[32];

    fb_fill(COLOR_DARK);
    fb_rect(0, 0, TFT_W, 10, status_color);
    draw_text(4, 2, "AIOT STATUS", COLOR_BLACK);

    if (sample->climate_valid) {
        snprintf(line, sizeof(line), "T:%.1fC H:%.0f%%", sample->temperature_c, sample->humidity_percent);
    } else {
        snprintf(line, sizeof(line), "T:-- H:--");
    }
    draw_text(4, 15, line, COLOR_WHITE);

    if (sample->air_valid) {
        snprintf(line, sizeof(line), "TVOC:%u HCHO:%u", sample->tvoc_ppb, sample->hcho_ug_m3);
    } else {
        snprintf(line, sizeof(line), "TVOC:-- HCHO:--");
    }
    draw_text(4, 27, line, COLOR_YELLOW);

    if (sample->air_valid) {
        snprintf(line, sizeof(line), "ECO2:%u LIGHT:%s", sample->eco2_ppm, light);
    } else {
        snprintf(line, sizeof(line), "ECO2:-- LIGHT:%s", light);
    }
    draw_text(4, 39, line, COLOR_CYAN);

    snprintf(line, sizeof(line), "AIR:%s SMOKE:%s", air, smoke);
    draw_text(4, 51, line, sample->smoke_detected ? COLOR_RED : status_color);

    snprintf(line, sizeof(line), "WINDOW:%s MANUAL:%s", control.window_open ? "OPEN" : "CLOSED",
             control.manual_override ? "YES" : "NO");
    draw_text(4, 63, line, control.window_open ? COLOR_GREEN : COLOR_WHITE);

    snprintf(line, sizeof(line), "ALARM:%s LED:%s", control.alarm_on ? "YES" : "NO", control.led_on ? "YES" : "NO");
    draw_text(4, 75, line, control.alarm_on ? COLOR_RED : COLOR_WHITE);

    draw_text(4, 91, status->cloud == APP_STATUS_LINK_READY ? "MQTT:ONLINE" : "MQTT:OFFLINE", COLOR_BLUE);

    tft_flush();
    return ESP_OK;
}
