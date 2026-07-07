idf_component_register(
    SRCS
        "main.c"
        "app_config.c"
        "mqtt_app.c"
    INCLUDE_DIRS
        "include"
    REQUIRES
        esp_event
        esp_netif
        esp_wifi
        mqtt
        nvs_flash
)

