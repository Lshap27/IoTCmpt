#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "driver/ledc.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_rom_sys.h"
#include "camera_app.h"
#include "wifi_app.h"
#include "http_upload.h"
#include "sensor_upload.h"

// ====================================================================
// =================== Wi-Fi / Upload 配置 ===========================
// ====================================================================

#define WIFI_SSID      "replace-with-local-ssid"
#define WIFI_PASSWORD  "replace-with-local-password"
#define UPLOAD_URL     "http://example.invalid/api/upload_image"

// ====================================================================
// =================== 0. 全局传感器数据结构 ==========================
// ====================================================================
// sensor_data_t 定义在 sensor_upload.h 中

static sensor_data_t g_sensor = {0};
static SemaphoreHandle_t g_data_mutex = NULL;

// ====================================================================
// =================== 硬件引脚宏定义 =================================
// ====================================================================

// TFT ST7735 128x128 SPI
#define TFT_SPI_HOST   SPI2_HOST
#define TFT_MOSI       6
#define TFT_SCLK       8
#define TFT_CS         10
#define TFT_DC         9
#define TFT_RST        46
#define TFT_BLK        7
#define TFT_W          128
#define TFT_H          128

// SG90舵机配置
#define SERVO_GPIO      36
#define SERVO_LEDC_CH   LEDC_CHANNEL_1
#define SERVO_TIMER     LEDC_TIMER_1
#define SERVO_FREQ      50
#define SERVO_MIN_US    500
#define SERVO_MAX_US    2500
#define SERVO_CLOSE_US  600
#define SERVO_OPEN_US   2200
#define SERVO_STEP_US   20
#define SERVO_STEP_DELAY pdMS_TO_TICKS(15)

// 单切换按键
#define KEY_TOGGLE_GPIO 21
#define KEY_LONG_TICK   pdMS_TO_TICKS(20)

// 有源蜂鸣器
#define BEEP_GPIO       35
#define BEEP_ON_LEVEL   0

// SHT30 软件 I2C
#define SHT30_ADDR  0x44
#define SHT30_CMD   0x2400

// TVOC301 UART
#define VOC_UART_NUM    UART_NUM_2
#define VOC_TX_GPIO     19
#define VOC_RX_GPIO     20
#define UART_BAUDRATE   9600
#define VOC_BUF_SIZE    128
#define FRAME_LEN       9
#define VOC_HEADER_0    0x2C
#define VOC_HEADER_1    0xE4

// LM393光敏
#define LM393_DO_GPIO   4

// ====================================================================
// =================== ST7735 寄存器 ==================================
// ====================================================================

#define ST7735_SWRESET 0x01
#define ST7735_SLPOUT  0x11
#define ST7735_NORON   0x13
#define ST7735_INVOFF  0x20
#define ST7735_INVON   0x21
#define ST7735_DISPON  0x29
#define ST7735_CASET   0x2A
#define ST7735_RASET   0x2B
#define ST7735_RAMWR   0x2C
#define ST7735_MADCTL  0x36
#define ST7735_COLMOD  0x3A

static const char *TAG_TFT = "TFT";
static const char *TAG_MAIN = "MAIN";
static spi_device_handle_t tft_spi = NULL;
static uint16_t fb[TFT_H][TFT_W];

// ====================================================================
// =================== TFT 驱动 =======================================
// ====================================================================

static void tft_cs(int level)  { gpio_set_level(TFT_CS, level); }
static void tft_dc(int level)  { gpio_set_level(TFT_DC, level); }

static void tft_spi_send(const uint8_t *data, size_t len)
{
    spi_transaction_t t = { .length = len * 8, .tx_buffer = data };
    spi_device_transmit(tft_spi, &t);
}

static void tft_cmd(uint8_t cmd)
{
    tft_dc(0); tft_cs(0); tft_spi_send(&cmd, 1); tft_cs(1);
}

static void tft_data(const uint8_t *d, size_t len)
{
    tft_dc(1); tft_cs(0); tft_spi_send(d, len); tft_cs(1);
}

static void tft_flush(void)
{
    uint8_t d[4];
    d[0]=0x00; d[1]=0x02; d[2]=0x00; d[3]=0x81;
    tft_cmd(ST7735_CASET); tft_data(d, 4);
    d[0]=0x00; d[1]=0x01; d[2]=0x00; d[3]=0x80;
    tft_cmd(ST7735_RASET); tft_data(d, 4);
    tft_cmd(ST7735_RAMWR);
    tft_dc(1); tft_cs(0);
    tft_spi_send((const uint8_t *)fb, TFT_W * TFT_H * 2);
    tft_cs(1);
}

static void tft_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL<<TFT_CS)|(1ULL<<TFT_DC)|(1ULL<<TFT_RST)|(1ULL<<TFT_BLK),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    gpio_config(&io);
    gpio_set_level(TFT_BLK, 1);
    gpio_set_level(TFT_CS, 1);
    gpio_set_level(TFT_DC, 0);
    gpio_set_level(TFT_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(5));

    gpio_set_level(TFT_RST, 1); vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(TFT_RST, 0); vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(TFT_RST, 1); vTaskDelay(pdMS_TO_TICKS(150));

    spi_bus_config_t bus = {
        .mosi_io_num=TFT_MOSI,.miso_io_num=-1,.sclk_io_num=TFT_SCLK,
        .quadwp_io_num=-1,.quadhd_io_num=-1,.max_transfer_sz=TFT_W*TFT_H*2
    };
    ESP_ERROR_CHECK(spi_bus_initialize(TFT_SPI_HOST, &bus, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t dev = {
        .clock_speed_hz=2000000,
        .mode=0,.spics_io_num=-1,.queue_size=1
    };
    ESP_ERROR_CHECK(spi_bus_add_device(TFT_SPI_HOST, &dev, &tft_spi));

    tft_cmd(ST7735_SWRESET); vTaskDelay(pdMS_TO_TICKS(150));
    tft_cmd(ST7735_SLPOUT);  vTaskDelay(pdMS_TO_TICKS(120));
    { uint8_t d[]={0x05}; tft_cmd(ST7735_COLMOD); tft_data(d,1); }
    { uint8_t d[]={0xC0}; tft_cmd(ST7735_MADCTL); tft_data(d,1); }
    tft_cmd(ST7735_INVON);
    tft_cmd(ST7735_NORON);   vTaskDelay(pdMS_TO_TICKS(10));
    tft_cmd(ST7735_DISPON);  vTaskDelay(pdMS_TO_TICKS(100));
    ESP_LOGI(TAG_TFT, "TFT OK");
}

// ====================================================================
// =================== 8x16 ASCII 字体 ===============================
// ====================================================================

static const uint8_t font_8x16[95][16] = {
    {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x18,0x3C,0x3C,0x3C,0x18,0x18,0x18,0x00,0x18,0x18,0x00,0x00,0x00,0x00},
    {0x00,0x66,0x66,0x66,0x24,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x6C,0x6C,0xFE,0x6C,0x6C,0x6C,0xFE,0x6C,0x6C,0x00,0x00,0x00,0x00},
    {0x18,0x18,0x7C,0xC6,0xC2,0xC0,0x7C,0x06,0x86,0xC6,0x7C,0x18,0x18,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0xC2,0xC6,0x0C,0x18,0x30,0x60,0xC6,0x86,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x38,0x6C,0x6C,0x38,0x76,0xDC,0xCC,0xCC,0xDC,0x76,0x00,0x00,0x00,0x00},
    {0x00,0x30,0x30,0x30,0x60,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x0C,0x18,0x30,0x30,0x30,0x30,0x30,0x30,0x18,0x0C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x30,0x18,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x18,0x30,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x66,0x3C,0xFF,0x3C,0x66,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x7E,0x18,0x18,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x18,0x30,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xFE,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x02,0x06,0x0C,0x18,0x30,0x60,0xC0,0x80,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x38,0x6C,0xC6,0xC6,0xD6,0xD6,0xC6,0xC6,0x6C,0x38,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x18,0x38,0x78,0x18,0x18,0x18,0x18,0x18,0x18,0x7E,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0x06,0x0C,0x18,0x30,0x60,0xC0,0xC6,0xFE,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0x06,0x06,0x3C,0x06,0x06,0x06,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x0C,0x1C,0x3C,0x6C,0xCC,0xFE,0x0C,0x0C,0x0C,0x1E,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFE,0xC0,0xC0,0xC0,0xFC,0x06,0x06,0x06,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x38,0x60,0xC0,0xC0,0xFC,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFE,0xC6,0x06,0x06,0x0C,0x18,0x30,0x30,0x30,0x30,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0xC6,0x7C,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0xC6,0x7E,0x06,0x06,0x06,0x0C,0x78,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x18,0x18,0x00,0x00,0x00,0x18,0x18,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x18,0x18,0x00,0x00,0x00,0x18,0x18,0x30,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x06,0x0C,0x18,0x30,0x60,0x30,0x18,0x0C,0x06,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x00,0xFE,0x00,0x00,0xFE,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x60,0x30,0x18,0x0C,0x06,0x0C,0x18,0x30,0x60,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0x0C,0x18,0x18,0x18,0x00,0x18,0x18,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x7C,0xC6,0xC6,0xDE,0xDE,0xDE,0xDC,0xC0,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x10,0x38,0x6C,0xC6,0xC6,0xFE,0xC6,0xC6,0xC6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFC,0x66,0x66,0x66,0x7C,0x66,0x66,0x66,0x66,0xFC,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x3C,0x66,0xC2,0xC0,0xC0,0xC0,0xC0,0xC2,0x66,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xF8,0x6C,0x66,0x66,0x66,0x66,0x66,0x66,0x6C,0xF8,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFE,0x66,0x62,0x68,0x78,0x68,0x60,0x62,0x66,0xFE,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFE,0x66,0x62,0x68,0x78,0x68,0x60,0x60,0x60,0xF0,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x3C,0x66,0xC2,0xC0,0xC0,0xDE,0xC6,0xC6,0x66,0x3A,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xC6,0xC6,0xC6,0xFE,0xC6,0xC6,0xC6,0xC6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x3C,0x18,0x18,0x18,0x18,0x18,0x18,0x18,0x18,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x1E,0x0C,0x0C,0x0C,0x0C,0x0C,0xCC,0xCC,0xCC,0x78,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xE6,0x66,0x6C,0x6C,0x78,0x78,0x6C,0x66,0x66,0xE6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xF0,0x60,0x60,0x60,0x60,0x60,0x60,0x62,0x66,0xFE,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xEE,0xFE,0xFE,0xD6,0xC6,0xC6,0xC6,0xC6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xE6,0xF6,0xFE,0xDE,0xCE,0xC6,0xC6,0xC6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFC,0x66,0x66,0x66,0x7C,0x60,0x60,0x60,0x60,0xF0,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xD6,0xDE,0x7C,0x0C,0x0E,0x00,0x00},
    {0x00,0x00,0xFC,0x66,0x66,0x66,0x7C,0x6C,0x66,0x66,0x66,0xE6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7C,0xC6,0xC6,0x60,0x38,0x0C,0x06,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x7E,0x7E,0x5A,0x18,0x18,0x18,0x18,0x18,0x18,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0x6C,0x38,0x10,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xC6,0xC6,0xC6,0xD6,0xD6,0xD6,0xFE,0xEE,0x6C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xC6,0xC6,0x6C,0x7C,0x38,0x38,0x7C,0x6C,0xC6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x66,0x66,0x66,0x66,0x3C,0x18,0x18,0x18,0x18,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xFE,0xC6,0x86,0x0C,0x18,0x30,0x60,0xC2,0xC6,0xFE,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x3C,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x80,0xC0,0xE0,0x70,0x38,0x1C,0x0E,0x06,0x02,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x3C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x3C,0x00,0x00,0x00,0x00},
    {0x10,0x38,0x6C,0xC6,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xFF,0x00,0x00},
    {0x30,0x30,0x18,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x78,0x0C,0x7C,0xCC,0xCC,0xCC,0x76,0x00,0x00,0x00,0x00},
    {0x00,0x00,0xE0,0x60,0x60,0x78,0x6C,0x66,0x66,0x66,0x66,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x7C,0xC6,0xC0,0xC0,0xC0,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x1C,0x0C,0x0C,0x3C,0x6C,0xCC,0xCC,0xCC,0xCC,0x76,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x7C,0xC6,0xFE,0xC0,0xC0,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x38,0x6C,0x64,0x60,0xF0,0x60,0x60,0x60,0x60,0xF0,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x76,0xCC,0xCC,0xCC,0xCC,0xCC,0x7C,0x0C,0xCC,0x78,0x00},
    {0x00,0x00,0xE0,0x60,0x60,0x6C,0x76,0x66,0x66,0x66,0x66,0xE6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x18,0x18,0x00,0x38,0x18,0x18,0x18,0x18,0x18,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x06,0x06,0x00,0x0E,0x06,0x06,0x06,0x06,0x06,0x06,0x66,0x66,0x3C,0x00},
    {0x00,0x00,0xE0,0x60,0x60,0x66,0x6C,0x78,0x78,0x6C,0x66,0xE6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x38,0x18,0x18,0x18,0x18,0x18,0x18,0x18,0x18,0x3C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xEC,0xFE,0xD6,0xD6,0xD6,0xD6,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xDC,0x66,0x66,0x66,0x66,0x66,0x66,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x7C,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xDC,0x66,0x66,0x66,0x66,0x66,0x7C,0x60,0x60,0xF0,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x76,0xCC,0xCC,0xCC,0xCC,0xCC,0x7C,0x0C,0x0C,0x1E,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xDC,0x76,0x66,0x60,0x60,0x60,0xF0,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x7C,0xC6,0x60,0x38,0x0C,0xC6,0x7C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x10,0x30,0x30,0xFC,0x30,0x30,0x30,0x30,0x36,0x1C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xCC,0xCC,0xCC,0xCC,0xCC,0xCC,0x76,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0x66,0x66,0x66,0x66,0x66,0x3C,0x18,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xC6,0xC6,0xD6,0xD6,0xD6,0xFE,0x6C,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xC6,0x6C,0x38,0x38,0x38,0x6C,0xC6,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0x7E,0x06,0x0C,0xF8,0x00},
    {0x00,0x00,0x00,0x00,0x00,0xFE,0xCC,0x18,0x30,0x60,0xC6,0xFE,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x0E,0x18,0x18,0x18,0x70,0x18,0x18,0x18,0x18,0x0E,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x18,0x18,0x18,0x18,0x00,0x18,0x18,0x18,0x18,0x18,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x70,0x18,0x18,0x18,0x0E,0x18,0x18,0x18,0x18,0x70,0x00,0x00,0x00,0x00},
    {0x00,0x00,0x76,0xDC,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
};

// ====================================================================
// =================== 绘图基础函数 ===================================
// ====================================================================

#define RGB565(r,g,b) ((((r)&0xF8)<<8)|(((g)&0xFC)<<3)|((b)>>3))
#define COLOR_BLACK     RGB565(0,0,0)
#define COLOR_WHITE     RGB565(255,255,255)
#define COLOR_RED       RGB565(255,60,60)
#define COLOR_GREEN     RGB565(60,255,60)
#define COLOR_YELLOW    RGB565(255,210,0)
#define COLOR_GRAY      RGB565(160,160,160)
#define COLOR_DARK_BG   RGB565(10,10,26)
#define COLOR_PANEL_BG  RGB565(26,26,46)
#define COLOR_TITLE_BG  RGB565(20,30,60)
#define COLOR_CYAN      RGB565(60,220,220)
#define COLOR_LINE      RGB565(50,50,80)

static void fb_fill(uint16_t color)
{
    for(int y=0;y<TFT_H;y++)
        for(int x=0;x<TFT_W;x++)
            fb[y][x]=color;
}

static void fb_fill_rect(int x,int y,int w,int h,uint16_t color)
{
    if(x<0){w+=x;x=0;}
    if(y<0){h+=y;y=0;}
    if(x+w>TFT_W)w=TFT_W-x;
    if(y+h>TFT_H)h=TFT_H-y;
    for(int j=0;j<h;j++)
        for(int i=0;i<w;i++)
            fb[y+j][x+i]=color;
}

static void fb_hline(int x,int y,int w,uint16_t color)
{
    fb_fill_rect(x,y,w,1,color);
}

static void fb_draw_char(int x,int y,char c,uint16_t fg,uint16_t bg)
{
    if(c<32||c>126)c='?';
    const uint8_t *glyph=font_8x16[c-32];
    for(int row=0;row<16;row++)
    {
        uint8_t bits=glyph[row];
        for(int col=0;col<8;col++)
        {
            int px=x+col,py=y+row;
            if(px>=0&&px<TFT_W&&py>=0&&py<TFT_H)
                fb[py][px]=(bits&0x80)?fg:bg;
            bits<<=1;
        }
    }
}

static void fb_draw_string(int x,int y,const char *str,uint16_t fg,uint16_t bg)
{
    while(*str){fb_draw_char(x,y,*str,fg,bg);x+=8;str++;}
}

static void fb_draw_string_center(int y,const char *str,uint16_t fg,uint16_t bg)
{
    int len=strlen(str);
    int x=(TFT_W-len*8)/2;
    fb_draw_string(x,y,str,fg,bg);
}

// ====================================================================
// =================== 蜂鸣器驱动 =====================================
// ====================================================================

static const char *TAG_BEEP = "BEEP";

static void beep_init(void)
{
    gpio_config_t cfg={
        .pin_bit_mask=1ULL<<BEEP_GPIO,
        .mode=GPIO_MODE_OUTPUT,
        .pull_up_en=GPIO_PULLUP_DISABLE,
        .pull_down_en=GPIO_PULLDOWN_DISABLE,
        .intr_type=GPIO_INTR_DISABLE
    };
    gpio_config(&cfg);
    gpio_set_level(BEEP_GPIO, !BEEP_ON_LEVEL);
    ESP_LOGI(TAG_BEEP,"Beep GPIO:%d active_level:%d",BEEP_GPIO,BEEP_ON_LEVEL);
}

static void beep_on(void)
{
    gpio_set_level(BEEP_GPIO, BEEP_ON_LEVEL);
}

static void beep_off(void)
{
    gpio_set_level(BEEP_GPIO, !BEEP_ON_LEVEL);
}

static void beep_alarm_loop(uint32_t ms_total)
{
    uint32_t start=xTaskGetTickCount()*portTICK_PERIOD_MS;
    while((xTaskGetTickCount()*portTICK_PERIOD_MS)-start<ms_total)
    {
        beep_on();vTaskDelay(pdMS_TO_TICKS(100));
        beep_off();vTaskDelay(pdMS_TO_TICKS(200));
    }
    beep_off();
}

// ====================================================================
// =================== SG90舵机驱动 ===================================
// ====================================================================

static const char *TAG_SERVO = "SERVO";
static uint16_t g_servo_current_us = 0;

static void servo_init(void)
{
    ledc_timer_config_t ledc_timer={
        .speed_mode=LEDC_LOW_SPEED_MODE,.timer_num=SERVO_TIMER,.duty_resolution=LEDC_TIMER_13_BIT,
        .freq_hz=SERVO_FREQ,.clk_cfg=LEDC_AUTO_CLK
    };
    ESP_ERROR_CHECK(ledc_timer_config(&ledc_timer));
    ledc_channel_config_t ledc_channel={
        .speed_mode=LEDC_LOW_SPEED_MODE,.channel=SERVO_LEDC_CH,.timer_sel=SERVO_TIMER,
        .intr_type=LEDC_INTR_DISABLE,.gpio_num=SERVO_GPIO,.duty=0,.hpoint=0
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ledc_channel));
    ESP_LOGI(TAG_SERVO,"Servo GPIO:%d",SERVO_GPIO);
}

static void servo_set_pulse(uint16_t pulse_us)
{
    if(pulse_us<SERVO_MIN_US)pulse_us=SERVO_MIN_US;
    if(pulse_us>SERVO_MAX_US)pulse_us=SERVO_MAX_US;
    uint32_t duty=(pulse_us*8192UL)/20000UL;
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE,SERVO_LEDC_CH,duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE,SERVO_LEDC_CH));
}

static void servo_smooth_turn(uint16_t target_us)
{
    uint16_t current_us = g_servo_current_us;
    if(target_us > current_us)
    {
        for(uint16_t p=current_us;p<=target_us;p+=SERVO_STEP_US)
        {servo_set_pulse(p);vTaskDelay(SERVO_STEP_DELAY);}
    }
    else if(target_us < current_us)
    {
        for(uint16_t p=current_us;p>=target_us;p-=SERVO_STEP_US)
        {servo_set_pulse(p);vTaskDelay(SERVO_STEP_DELAY);}
    }
    servo_set_pulse(target_us);
    g_servo_current_us = target_us;
}

static void servo_smooth_open(void)
{
    ESP_LOGI(TAG_SERVO,"Smooth Open");
    servo_smooth_turn(SERVO_OPEN_US);
}

static void servo_smooth_close(void)
{
    ESP_LOGI(TAG_SERVO,"Smooth Close");
    servo_smooth_turn(SERVO_CLOSE_US);
}

// ====================================================================
// =================== 按键任务 =======================================
// ====================================================================

static const char *TAG_KEY = "KEY";

static void key_task(void *arg)
{
    gpio_config_t key_cfg={
        .pin_bit_mask=1ULL<<KEY_TOGGLE_GPIO,.mode=GPIO_MODE_INPUT,
        .pull_up_en=GPIO_PULLUP_ENABLE,.pull_down_en=GPIO_PULLDOWN_DISABLE,.intr_type=GPIO_INTR_DISABLE
    };
    ESP_ERROR_CHECK(gpio_config(&key_cfg));
    ESP_LOGI(TAG_KEY,"Key GPIO:%d init OK",KEY_TOGGLE_GPIO);
    bool last_key_state=true;
    while(1)
    {
        bool press_now=(gpio_get_level(KEY_TOGGLE_GPIO)==0);
        if(press_now&&!last_key_state)
        {
            vTaskDelay(KEY_LONG_TICK);
            if(gpio_get_level(KEY_TOGGLE_GPIO)==0)
            {
                ESP_LOGI(TAG_KEY,"Button pressed - toggle window");
                if(xSemaphoreTake(g_data_mutex,pdMS_TO_TICKS(100))==pdTRUE)
                {
                    g_sensor.manual_override=true;
                    g_sensor.manual_open=!g_sensor.manual_open;
                    g_sensor.beep_alarm=false;
                    xSemaphoreGive(g_data_mutex);
                }
            }
        }
        last_key_state=press_now;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

// ====================================================================
// =================== 舵机控制任务 ===================================
// ====================================================================

static void servo_task(void *arg)
{
    servo_init();
    beep_init();
    servo_set_pulse(SERVO_CLOSE_US);
    g_servo_current_us = SERVO_CLOSE_US;
    vTaskDelay(pdMS_TO_TICKS(500));
    bool window_is_open = false;
    while(1)
    {
        sensor_data_t local;
        if(xSemaphoreTake(g_data_mutex,pdMS_TO_TICKS(100))==pdTRUE)
        {
            memcpy(&local,&g_sensor,sizeof(sensor_data_t));
            xSemaphoreGive(g_data_mutex);
        }
        else
        {
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }
        bool auto_force_open = (local.need_open_window && !window_is_open);
        if(auto_force_open)
        {
            ESP_LOGI(TAG_SERVO,">>> AUTO-FORCE OPEN <<<");
            beep_alarm_loop(3000);
            servo_smooth_open();
            window_is_open = true;
            if(xSemaphoreTake(g_data_mutex,pdMS_TO_TICKS(100))==pdTRUE)
            {
                g_sensor.manual_open = true;
                xSemaphoreGive(g_data_mutex);
            }
        }
        else if(local.manual_override && local.manual_open != window_is_open)
        {
            ESP_LOGI(TAG_SERVO,">>> MANUAL %s <<<",
                     local.manual_open?"OPEN":"CLOSE");
            beep_off();
            if(local.manual_open)
            {
                servo_smooth_open();
                window_is_open = true;
            }
            else
            {
                servo_smooth_close();
                window_is_open = false;
            }
        }
        else
        {
            beep_off();
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

// ====================================================================
// =================== 环境评估 =======================================
// ====================================================================

typedef enum { STATUS_GOOD, STATUS_WARN, STATUS_BAD } air_status_t;

static void evaluate_environment(sensor_data_t *d, air_status_t *out, char *advice, size_t len)
{
    air_status_t worst=STATUS_GOOD;
    char buf[256];
    int p=0;
    if(d->sht30_valid)
    {
        if(d->temperature>32.0f)
        {
            worst=STATUS_BAD;
            p+=snprintf(buf+p,sizeof(buf)-p,"!!TEMP CRIT %.1f!!\nOpen window/AC\n",d->temperature);
        }
        else if(d->temperature>28.0f)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"Temp high %.1fC\nOpen window\n",d->temperature);
        }
        if(d->humidity>75.0f)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"Humid high %.1f%%\nDehumid/Ventilate\n",d->humidity);
        }
        else if(d->humidity<30.0f)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"Humid low %.1f%%\nUse humidifier\n",d->humidity);
        }
    }
    if(d->tvoc_valid)
    {
        if(d->tvoc>600)
        {
            worst=STATUS_BAD;
            p+=snprintf(buf+p,sizeof(buf)-p,"!!TVOC CRIT %d!!\nOpen window NOW\n",d->tvoc);
        }
        else if(d->tvoc>300)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"TVOC high %d\nOpen window\n",d->tvoc);
        }
        if(d->hcho>100)
        {
            worst=STATUS_BAD;
            p+=snprintf(buf+p,sizeof(buf)-p,"!!HCHO CRIT %d!!\nEVACUATE!!\n",d->hcho);
        }
        else if(d->hcho>60)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"HCHO high %d\nOpen window\n",d->hcho);
        }
        if(d->eco2>1500)
        {
            worst=STATUS_BAD;
            p+=snprintf(buf+p,sizeof(buf)-p,"!!CO2 CRIT %d!!\nOpen window NOW\n",d->eco2);
        }
        else if(d->eco2>1000)
        {
            if(worst<STATUS_WARN)worst=STATUS_WARN;
            p+=snprintf(buf+p,sizeof(buf)-p,"CO2 high %d\nVentilate\n",d->eco2);
        }
    }
    if(d->light_valid&&d->light_dark)
        p+=snprintf(buf+p,sizeof(buf)-p,"Dim light\nTurn on light\n");
    if(worst==STATUS_GOOD&&(d->sht30_valid||d->tvoc_valid))
        snprintf(buf,sizeof(buf),"Air quality GOOD\nNo action needed\n");
    if(out) *out=worst;
    if(advice&&len>0)
    {
        strncpy(advice,buf,len-1);
        advice[len-1]='\0';
    }
    d->need_open_window = (worst==STATUS_WARN||worst==STATUS_BAD);
    if(!d->manual_override)
    {
        d->beep_alarm = d->need_open_window;
    }
}

// ====================================================================
// =================== UI屏幕渲染 =====================================
// ====================================================================

static void ui_render(sensor_data_t *d)
{
    char buf[16];
    fb_fill(COLOR_DARK_BG);
    fb_fill_rect(0,0,TFT_W,17,COLOR_TITLE_BG);
    fb_draw_string_center(0,"= Env Monitor =",COLOR_WHITE,COLOR_TITLE_BG);
    if(d->sht30_valid)
    {
        snprintf(buf,sizeof(buf),"%.1fC",d->temperature);
        uint16_t tc=(d->temperature>32)?COLOR_RED:(d->temperature>28)?COLOR_YELLOW:COLOR_GREEN;
        uint16_t hc=(d->humidity>75||d->humidity<30)?COLOR_YELLOW:COLOR_GREEN;
        int tx=4;
        fb_draw_string(tx,18,"T:",COLOR_GRAY,COLOR_DARK_BG);tx+=16;
        fb_draw_string(tx,18,buf,tc,COLOR_DARK_BG);tx+=strlen(buf)*8;
        fb_draw_string(tx,18," H:",COLOR_GRAY,COLOR_DARK_BG);tx+=24;
        snprintf(buf,sizeof(buf),"%.1f%%",d->humidity);
        fb_draw_string(tx,18,buf,hc,COLOR_DARK_BG);
    }
    else
        fb_draw_string(4,18,"T:--.-C H:--.-*%*",COLOR_GRAY,COLOR_DARK_BG);
    if(d->tvoc_valid)
    {
        snprintf(buf,sizeof(buf),"%d",d->tvoc);
        uint16_t vc=(d->tvoc>600)?COLOR_RED:(d->tvoc>300)?COLOR_YELLOW:COLOR_GREEN;
        uint16_t cc=(d->eco2>1500)?COLOR_RED:(d->eco2>1000)?COLOR_YELLOW:COLOR_GREEN;
        int tx=4;
        fb_draw_string(tx,34,"V:",COLOR_GRAY,COLOR_DARK_BG);tx+=16;
        fb_draw_string(tx,34,buf,vc,COLOR_DARK_BG);tx+=strlen(buf)*8;
        fb_draw_string(tx,34," C:",COLOR_GRAY,COLOR_DARK_BG);tx+=24;
        snprintf(buf,sizeof(buf),"%d",d->eco2);
        fb_draw_string(tx,34,buf,cc,COLOR_DARK_BG);
    }
    else
        fb_draw_string(4,34,"V:--- C:---",COLOR_GRAY,COLOR_DARK_BG);
    {
        uint16_t hc=COLOR_GRAY;
        snprintf(buf,sizeof(buf),"---");
        if(d->tvoc_valid)
        {
            snprintf(buf,sizeof(buf),"%d",d->hcho);
            hc=(d->hcho>100)?COLOR_RED:(d->hcho>60)?COLOR_YELLOW:COLOR_GREEN;
        }
        int tx=4;
        fb_draw_string(tx,50,"F:",COLOR_GRAY,COLOR_DARK_BG);tx+=16;
        fb_draw_string(tx,50,buf,hc,COLOR_DARK_BG);tx+=strlen(buf)*8;
        fb_draw_string(tx,50," L:",COLOR_GRAY,COLOR_DARK_BG);tx+=24;
        if(d->light_valid)
            fb_draw_string(tx,50,d->light_dark?"DIM":"BRT",d->light_dark?COLOR_YELLOW:COLOR_GREEN,COLOR_DARK_BG);
        else
            fb_draw_string(tx,50,"---",COLOR_GRAY,COLOR_DARK_BG);
    }
    fb_hline(0,68,TFT_W,COLOR_LINE);
    {
        uint16_t status_color;
        const char *status_text;
        if(d->need_open_window)
        {
            status_color=COLOR_RED;
            status_text="AIR BAD - OPEN WINDOW!";
        }
        else if(d->sht30_valid||d->tvoc_valid)
        {
            status_color=COLOR_GREEN;
            status_text="AIR GOOD";
        }
        else
        {
            status_color=COLOR_GRAY;
            status_text="WAITING DATA...";
        }
        int text_len=strlen(status_text);
        int text_x=(TFT_W-text_len*8)/2;
        fb_fill_rect(0,72,TFT_W,18,COLOR_PANEL_BG);
        fb_draw_string(text_x,73,status_text,status_color,COLOR_PANEL_BG);
    }
    {
        fb_fill_rect(0,92,TFT_W,18,COLOR_PANEL_BG);
        if(d->manual_override)
        {
            if(d->manual_open)
                fb_draw_string_center(93,"[MANUAL] Window: OPEN",COLOR_YELLOW,COLOR_PANEL_BG);
            else
                fb_draw_string_center(93,"[MANUAL] Window: CLOSED",COLOR_CYAN,COLOR_PANEL_BG);
        }
        else
        {
            if(d->need_open_window)
                fb_draw_string_center(93,"[AUTO] Window: OPEN",COLOR_GREEN,COLOR_PANEL_BG);
            else
                fb_draw_string_center(93,"[AUTO] Window: CLOSED",COLOR_GRAY,COLOR_PANEL_BG);
        }
    }
    fb_draw_string_center(112,"Btn:Toggle Window",COLOR_GRAY,COLOR_DARK_BG);
}

// ====================================================================
// =================== SHT30 软件 I2C =================================
// ====================================================================

#define SHT30_SDA   1
#define SHT30_SCL   2
#define SHT30_I2C_DELAY  5

static void sht30_sda_out(void)
{
    gpio_set_direction(SHT30_SDA, GPIO_MODE_OUTPUT_OD);
}

static void sht30_sda_in(void)
{
    gpio_set_direction(SHT30_SDA, GPIO_MODE_INPUT);
}

static void sht30_scl_low(void)  { gpio_set_level(SHT30_SCL, 0); }
static void sht30_scl_high(void) { gpio_set_level(SHT30_SCL, 1); }
static void sht30_sda_low(void)  { gpio_set_level(SHT30_SDA, 0); }
static void sht30_sda_high(void) { gpio_set_level(SHT30_SDA, 1); }
static int  sht30_sda_read(void) { return gpio_get_level(SHT30_SDA); }

static void sht30_i2c_start(void)
{
    sht30_sda_out();
    sht30_sda_high();
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY);
    sht30_sda_low();
    esp_rom_delay_us(SHT30_I2C_DELAY);
    sht30_scl_low();
}

static void sht30_i2c_stop(void)
{
    sht30_sda_out();
    sht30_sda_low();
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY);
    sht30_sda_high();
    esp_rom_delay_us(SHT30_I2C_DELAY);
}

static bool sht30_i2c_write_byte(uint8_t byte)
{
    sht30_sda_out();
    for (int i = 7; i >= 0; i--) {
        if (byte & (1 << i))
            sht30_sda_high();
        else
            sht30_sda_low();
        esp_rom_delay_us(SHT30_I2C_DELAY / 2);
        sht30_scl_high();
        esp_rom_delay_us(SHT30_I2C_DELAY);
        sht30_scl_low();
        esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    }
    sht30_sda_in();
    sht30_sda_high();
    esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    bool ack = (sht30_sda_read() == 0);
    esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    sht30_scl_low();
    sht30_sda_out();
    return ack;
}

static uint8_t sht30_i2c_read_byte(bool send_ack)
{
    uint8_t byte = 0;
    sht30_sda_in();
    sht30_sda_high();
    for (int i = 7; i >= 0; i--) {
        esp_rom_delay_us(SHT30_I2C_DELAY / 2);
        sht30_scl_high();
        esp_rom_delay_us(SHT30_I2C_DELAY / 2);
        if (sht30_sda_read())
            byte |= (1 << i);
        sht30_scl_low();
    }
    sht30_sda_out();
    if (send_ack)
        sht30_sda_low();
    else
        sht30_sda_high();
    esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    sht30_scl_high();
    esp_rom_delay_us(SHT30_I2C_DELAY);
    sht30_scl_low();
    esp_rom_delay_us(SHT30_I2C_DELAY / 2);
    sht30_sda_in();
    return byte;
}

static void sht30_init(void)
{
    gpio_config_t io_cfg = {
        .pin_bit_mask = (1ULL << SHT30_SDA) | (1ULL << SHT30_SCL),
        .mode = GPIO_MODE_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_cfg);
    gpio_set_level(SHT30_SDA, 1);
    gpio_set_level(SHT30_SCL, 1);
    ESP_LOGI("SHT30", "Soft I2C init OK (SCL=GPIO%d SDA=GPIO%d)", SHT30_SCL, SHT30_SDA);
}

static bool sht30_read(float *temp, float *hum)
{
    sht30_i2c_start();
    if (!sht30_i2c_write_byte((SHT30_ADDR << 1) | 0)) {
        sht30_i2c_stop();
        ESP_LOGW("SHT30", "Addr ACK fail (write)");
        return false;
    }
    sht30_i2c_write_byte((SHT30_CMD >> 8) & 0xFF);
    sht30_i2c_write_byte(SHT30_CMD & 0xFF);
    sht30_i2c_stop();
    vTaskDelay(pdMS_TO_TICKS(30));
    sht30_i2c_start();
    if (!sht30_i2c_write_byte((SHT30_ADDR << 1) | 1)) {
        sht30_i2c_stop();
        ESP_LOGW("SHT30", "Addr ACK fail (read)");
        return false;
    }
    uint8_t data[6];
    for (int i = 0; i < 6; i++)
        data[i] = sht30_i2c_read_byte(i < 5);
    sht30_i2c_stop();
    uint16_t raw_temp = (data[0] << 8) | data[1];
    uint16_t raw_hum  = (data[3] << 8) | data[4];
    *temp = -45.0f + 175.0f * ((float)raw_temp / 65535.0f);
    *hum  = 100.0f * ((float)raw_hum / 65535.0f);
    ESP_LOGI("SHT30", "T=%.1fC H=%.1f%%", *temp, *hum);
    return true;
}

// ====================================================================
// =================== TVOC301 传感器 UART ============================
// ====================================================================

static void voc_uart_init(void)
{
    gpio_config_t rx_pullup={
        .pin_bit_mask=1ULL<<VOC_RX_GPIO,
        .mode=GPIO_MODE_INPUT,
        .pull_up_en=GPIO_PULLUP_ENABLE,
        .pull_down_en=GPIO_PULLDOWN_DISABLE,
        .intr_type=GPIO_INTR_DISABLE
    };
    gpio_config(&rx_pullup);
    uart_config_t uart_config={
        .baud_rate=UART_BAUDRATE,
        .data_bits=UART_DATA_8_BITS,
        .parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1,
        .flow_ctrl=UART_HW_FLOWCTRL_DISABLE,
        .source_clk=UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(VOC_UART_NUM,VOC_BUF_SIZE*2,0,0,NULL,0));
    ESP_ERROR_CHECK(uart_param_config(VOC_UART_NUM,&uart_config));
    ESP_ERROR_CHECK(uart_set_pin(VOC_UART_NUM,VOC_TX_GPIO,VOC_RX_GPIO,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
    ESP_LOGI("TVOC","UART init OK, baud=%d",UART_BAUDRATE);
}

// ====================================================================
// =================== LM393 光敏传感器 ===============================
// ====================================================================

static void lm393_init(void)
{
    gpio_config_t cfg={
        .pin_bit_mask=1ULL<<LM393_DO_GPIO,
        .mode=GPIO_MODE_INPUT,
        .pull_up_en=GPIO_PULLUP_DISABLE,
        .pull_down_en=GPIO_PULLDOWN_DISABLE,
        .intr_type=GPIO_INTR_DISABLE
    };
    gpio_config(&cfg);
    ESP_LOGI("LM393","GPIO init OK");
}

// ====================================================================
// =================== 传感器读取任务 =================================
// ====================================================================

static void sensor_task(void *arg)
{
    sht30_init();
    voc_uart_init();
    lm393_init();

    // 等待传感器稳定
    vTaskDelay(pdMS_TO_TICKS(1000));

    while(1)
    {
        // ========== 读取 SHT30 ==========
        float temp=0, hum=0;
        bool sht_ok = sht30_read(&temp, &hum);
        if(!sht_ok) {
            ESP_LOGW("SENSOR", "SHT30读取失败");
        }

        // ========== 读取 TVOC301 ==========
        bool voc_ok=false;
        uint16_t tvoc=0, hcho=0, eco2=0;
        uart_flush_input(VOC_UART_NUM);
        {
            uint8_t sniff[64];
            int sniff_len = uart_read_bytes(VOC_UART_NUM, sniff, sizeof(sniff), pdMS_TO_TICKS(1000));
            if(sniff_len > 0)
            {
                for(int i=0; i <= sniff_len - FRAME_LEN; i++)
                {
                    if(sniff[i] == VOC_HEADER_0 && sniff[i+1] == VOC_HEADER_1)
                    {
                        uint8_t sum=0;
                        for(int j=0; j<FRAME_LEN-1; j++) sum += sniff[i+j];
                        if(sum == sniff[i+FRAME_LEN-1])
                        {
                            tvoc = (sniff[i+2] << 8) | sniff[i+3];
                            hcho = (sniff[i+4] << 8) | sniff[i+5];
                            eco2 = (sniff[i+6] << 8) | sniff[i+7];
                            voc_ok = true;
                            ESP_LOGI("TVOC", "TVOC=%dppb HCHO=%dug/m3 CO2=%dppm", tvoc, hcho, eco2);
                            break;
                        }
                    }
                }
            }
        }

        // ========== 读取 LM393 ==========
        int lm393_level = gpio_get_level(LM393_DO_GPIO);

        // ========== 更新全局数据结构 ==========
        if(xSemaphoreTake(g_data_mutex, pdMS_TO_TICKS(200)) == pdTRUE)
        {
            if(sht_ok)
            {
                g_sensor.temperature = temp;
                g_sensor.humidity = hum;
                g_sensor.sht30_valid = true;
            }
            else
            {
                g_sensor.sht30_valid = false;
            }

            if(voc_ok)
            {
                g_sensor.tvoc = tvoc;
                g_sensor.hcho = hcho;
                g_sensor.eco2 = eco2;
                g_sensor.tvoc_valid = true;
            }
            else
            {
                g_sensor.tvoc_valid = false;
            }

            g_sensor.light_dark = (lm393_level == 0) ? 1 : 0;
            g_sensor.light_valid = true;

            // 环境评估
            evaluate_environment(&g_sensor, NULL, NULL, 0);

            // 复制数据用于HTTP上传
            sensor_data_t upload_data;
            memcpy(&upload_data, &g_sensor, sizeof(sensor_data_t));
            xSemaphoreGive(g_data_mutex);

            // ============================================================
            // 🔥 HTTP上传传感器数据到后端
            // ============================================================
            esp_err_t ret = upload_sensor_data(&upload_data);
            if (ret == ESP_OK) {
                ESP_LOGI("SENSOR", "✅ 传感器数据上报成功");
            } else {
                ESP_LOGW("SENSOR", "⚠️ 传感器数据上报失败，下次重试");
            }
        }

        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}

// ====================================================================
// =================== UI渲染任务 =====================================
// ====================================================================

static void ui_task(void *arg)
{
    tft_init();
    // 诊断：先刷全屏红色确认 SPI 通信正常
    fb_fill(COLOR_RED);
    tft_flush();
    vTaskDelay(pdMS_TO_TICKS(800));
    // 启动画面
    fb_fill(COLOR_DARK_BG);
    fb_draw_string_center(40,"SG90 Smart Window",COLOR_WHITE,COLOR_DARK_BG);
    fb_draw_string_center(60,"Starting up...",COLOR_GREEN,COLOR_DARK_BG);
    fb_draw_string_center(80,"SHT30 + TVOC + LM393",COLOR_GRAY,COLOR_DARK_BG);
    tft_flush();
    vTaskDelay(pdMS_TO_TICKS(1500));
    ESP_LOGI("UI","Display init OK");
    while(1)
    {
        sensor_data_t local = {0};
        if(xSemaphoreTake(g_data_mutex,pdMS_TO_TICKS(200))==pdTRUE)
        {
            memcpy(&local,&g_sensor,sizeof(sensor_data_t));
            xSemaphoreGive(g_data_mutex);
        }
        ui_render(&local);
        tft_flush();
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

// ====================================================================
// =================== 摄像头抓拍上传任务 =============================
// ====================================================================

static void camera_upload_task(void *arg)
{
    int fail_count = 0;
    int upload_fail_count = 0;
    while (1) {
        camera_fb_t *fb = camera_app_capture();
        if (fb) {
            fail_count = 0;
            esp_err_t err = http_upload_jpeg(UPLOAD_URL, fb->buf, fb->len);
            if (err == ESP_OK) {
                upload_fail_count = 0;
                ESP_LOGI(TAG_MAIN, "Image upload success");
            } else {
                upload_fail_count++;
                if (upload_fail_count == 1 || upload_fail_count % 30 == 0) {
                    ESP_LOGW(TAG_MAIN, "Upload fail (%d times) --- server unreachable", upload_fail_count);
                }
            }
            camera_app_return_frame(fb);
            vTaskDelay(pdMS_TO_TICKS(5000));
        } else {
            fail_count++;
            if (fail_count == 1 || fail_count % 10 == 0) {
                ESP_LOGW(TAG_MAIN, "Camera capture failed (%d times)", fail_count);
            }
            if (fail_count == 5) {
                ESP_LOGI(TAG_MAIN, "Attempting camera re-init...");
                esp_camera_deinit();
                vTaskDelay(pdMS_TO_TICKS(500));
                if (camera_app_init() == ESP_OK) {
                    ESP_LOGI(TAG_MAIN, "Camera re-init OK");
                    fail_count = 0;
                } else {
                    ESP_LOGW(TAG_MAIN, "Camera re-init failed, will retry later");
                }
            }
            vTaskDelay(pdMS_TO_TICKS(10000));
        }
    }
}

// ====================================================================
// =================== APP MAIN =======================================
// ====================================================================

void app_main(void)
{
    ESP_LOGI(TAG_MAIN, "System starting...");

    // ========== Wi-Fi 初始化 ==========
    if (wifi_app_init_sta(WIFI_SSID, WIFI_PASSWORD) != ESP_OK) {
        ESP_LOGE(TAG_MAIN, "Wi-Fi init failed");
        return;
    }

    // ========== 摄像头初始化 ==========
    bool camera_ok = (camera_app_init() == ESP_OK);
    if (!camera_ok) {
        ESP_LOGW(TAG_MAIN, "Camera init failed --- continuing without camera");
    }

    // ========== 全局数据互斥量 ==========
    g_data_mutex = xSemaphoreCreateMutex();
    assert(g_data_mutex != NULL);

    // ========== 初始化全局数据默认值 ==========
    g_sensor.manual_override = false;
    g_sensor.manual_open = false;
    g_sensor.need_open_window = false;
    g_sensor.beep_alarm = false;

    // ========== 提前关闭蜂鸣器 ==========
    gpio_config_t beep_pre = {
        .pin_bit_mask = 1ULL << BEEP_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    gpio_config(&beep_pre);
    gpio_set_level(BEEP_GPIO, !BEEP_ON_LEVEL);

    // ========== 创建全部任务 ==========
    // 传感器任务 (SHT30 + TVOC301 + LM393 + 环境评估 + HTTP上传)
    xTaskCreate(sensor_task, "sensor_task", 8192, NULL, 3, NULL);

    // 舵机 + 蜂鸣器控制任务
    xTaskCreate(servo_task, "servo_task", 4096, NULL, 4, NULL);

    // 按键检测任务
    xTaskCreate(key_task, "key_task", 3072, NULL, 2, NULL);

    // TFT 显示任务
    xTaskCreate(ui_task, "ui_task", 4096, NULL, 5, NULL);

    // 摄像头抓拍上传任务（仅摄像头初始化成功后创建）
    if (camera_ok) {
        xTaskCreate(camera_upload_task, "camera_task", 4096, NULL, 1, NULL);
    }

    ESP_LOGI(TAG_MAIN, "System started OK --- all tasks running");
}
