#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Start Wi-Fi station mode and connect in the background.
 * Requires esp_netif_init() and the default event loop.
 * Reconnects automatically with exponential backoff; never blocks.
 * Returns ESP_ERR_INVALID_ARG if no SSID is configured.
 */
esp_err_t network_manager_start(const char *ssid, const char *password, uint32_t max_backoff_ms);

bool network_manager_is_connected(void);

/** Wait until an IP address is assigned. Returns false on timeout. */
bool network_manager_wait_connected(TickType_t timeout);

#ifdef __cplusplus
}
#endif
