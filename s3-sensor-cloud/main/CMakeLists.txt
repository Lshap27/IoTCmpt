idf_component_register(SRCS
    "main.c"
    "sensor_upload.c"
    "camera_app.c"
    "http_upload.c"
    "wifi_app.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_http_client
        json
        esp_wifi
        nvs_flash
        esp_netif
        esp_event
        driver
        esp_lcd
        # 你原有的其他组件
)