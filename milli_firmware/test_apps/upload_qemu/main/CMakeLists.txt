idf_component_register(
    SRCS
        "test_main.c"
        "../../../main/image_uploader.c"
        "../../../main/capture_policy.c"
    INCLUDE_DIRS "." "../../../main"
    PRIV_REQUIRES
        esp_eth
        esp_netif
        esp_event
        esp_timer
        esp_http_client
        esp_psram
        mbedtls
)
