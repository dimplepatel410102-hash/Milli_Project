#include "network_manager.h"

#include <stdlib.h>
#include <string.h>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/event_groups.h"

static const char *TAG = "network";

#define CONNECTED_BIT BIT0
#define INITIAL_BACKOFF_MS 1000

static EventGroupHandle_t s_events;
static esp_timer_handle_t s_reconnect_timer;
static uint32_t s_backoff_ms = INITIAL_BACKOFF_MS;
static uint32_t s_max_backoff_ms;
static char s_ssid[33];
static bool s_scan_done_once;

#define SCAN_MAX_RESULTS 20

static const char *reason_hint(uint8_t reason)
{
    switch (reason) {
    case WIFI_REASON_NO_AP_FOUND:
        return "network not found: the ESP32-S3 only sees 2.4 GHz networks";
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_AUTH_EXPIRE:
        return "authentication failed: check the Wi-Fi password";
    case WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY:
    case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
        return "network found but its security mode is not supported";
    case WIFI_REASON_BEACON_TIMEOUT:
        return "signal lost";
    case WIFI_REASON_ASSOC_TOOMANY:
        return "access point refused the connection: its device limit is reached or this MAC is blocked";
    default:
        return "see ESP-IDF wifi_err_reason_t";
    }
}

static void log_scan_results(void)
{
    uint16_t count = SCAN_MAX_RESULTS;
    wifi_ap_record_t *records = calloc(count, sizeof(wifi_ap_record_t));
    if (records == NULL || esp_wifi_scan_get_ap_records(&count, records) != ESP_OK) {
        free(records);
        esp_wifi_clear_ap_list();
        return;
    }
    if (count == 0) {
        ESP_LOGW(TAG, "scan: no 2.4 GHz networks in range");
    } else {
        ESP_LOGW(TAG, "scan: 2.4 GHz networks the ESP32 can see (use one of these as the SSID):");
        for (uint16_t i = 0; i < count; i++) {
            ESP_LOGW(TAG, "  \"%s\"  channel %d  signal %d dBm%s", (const char *)records[i].ssid,
                     records[i].primary, records[i].rssi,
                     strcmp((const char *)records[i].ssid, s_ssid) == 0 ? "  <- configured" : "");
        }
    }
    free(records);
}

static void reconnect_cb(void *arg)
{
    esp_err_t err = esp_wifi_connect();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_connect failed: %s", esp_err_to_name(err));
    }
}

static void schedule_reconnect(void)
{
    ESP_LOGI(TAG, "reconnecting in %lu ms", (unsigned long)s_backoff_ms);
    esp_timer_stop(s_reconnect_timer);
    esp_timer_start_once(s_reconnect_timer, (uint64_t)s_backoff_ms * 1000);
    s_backoff_ms = s_backoff_ms * 2 > s_max_backoff_ms ? s_max_backoff_ms : s_backoff_ms * 2;
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Wi-Fi started, connecting");
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = (const wifi_event_sta_disconnected_t *)data;
        xEventGroupClearBits(s_events, CONNECTED_BIT);
        ESP_LOGW(TAG, "Wi-Fi disconnected (reason %d: %s)", event->reason, reason_hint(event->reason));
        if (event->reason == WIFI_REASON_NO_AP_FOUND && !s_scan_done_once) {
            s_scan_done_once = true;
            ESP_LOGW(TAG, "SSID \"%s\" not found; scanning for visible networks", s_ssid);
            if (esp_wifi_scan_start(NULL, false) == ESP_OK) {
                return;
            }
        }
        schedule_reconnect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        log_scan_results();
        schedule_reconnect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = (const ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "Wi-Fi connected, IP " IPSTR ", gateway " IPSTR,
                 IP2STR(&event->ip_info.ip), IP2STR(&event->ip_info.gw));
        s_backoff_ms = INITIAL_BACKOFF_MS;
        xEventGroupSetBits(s_events, CONNECTED_BIT);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        ESP_LOGW(TAG, "IP address lost");
        xEventGroupClearBits(s_events, CONNECTED_BIT);
    }
}

esp_err_t network_manager_start(const char *ssid, const char *password, uint32_t max_backoff_ms)
{
    if (ssid == NULL || ssid[0] == '\0') {
        ESP_LOGE(TAG, "Wi-Fi SSID is not configured (idf.py menuconfig -> Milli configuration -> Wi-Fi)");
        return ESP_ERR_INVALID_ARG;
    }
    if (strlen(ssid) > 32 || (password != NULL && strlen(password) > 63)) {
        ESP_LOGE(TAG, "Wi-Fi SSID (max 32) or password (max 63) is too long");
        return ESP_ERR_INVALID_ARG;
    }

    s_events = xEventGroupCreate();
    if (s_events == NULL) {
        return ESP_ERR_NO_MEM;
    }
    s_max_backoff_ms = max_backoff_ms;
    strlcpy(s_ssid, ssid, sizeof(s_ssid));

    const esp_timer_create_args_t timer_args = {.callback = reconnect_cb, .name = "wifi_reconnect"};
    esp_err_t err = esp_timer_create(&timer_args, &s_reconnect_timer);
    if (err != ESP_OK) {
        return err;
    }

    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&init_cfg);
    if (err != ESP_OK) {
        return err;
    }

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_LOST_IP, on_event, NULL));

    wifi_config_t wifi_cfg = {0};
    strlcpy((char *)wifi_cfg.sta.ssid, ssid, sizeof(wifi_cfg.sta.ssid));
    if (password != NULL && password[0] != '\0') {
        strlcpy((char *)wifi_cfg.sta.password, password, sizeof(wifi_cfg.sta.password));
        wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        wifi_cfg.sta.threshold.authmode = WIFI_AUTH_OPEN;
    }
    wifi_cfg.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    // Power save adds latency to every upload; keep the radio awake.
    esp_wifi_set_ps(WIFI_PS_NONE);
    err = esp_wifi_start();
    if (err == ESP_OK) {
        uint8_t mac[6] = {0};
        esp_wifi_get_mac(WIFI_IF_STA, mac);
        ESP_LOGI(TAG, "connecting to SSID \"%s\" as MAC %02x:%02x:%02x:%02x:%02x:%02x", ssid, mac[0], mac[1], mac[2],
                 mac[3], mac[4], mac[5]);
    }
    return err;
}

bool network_manager_is_connected(void)
{
    return s_events != NULL && (xEventGroupGetBits(s_events) & CONNECTED_BIT);
}

bool network_manager_wait_connected(TickType_t timeout)
{
    if (s_events == NULL) {
        return false;
    }
    return xEventGroupWaitBits(s_events, CONNECTED_BIT, pdFALSE, pdTRUE, timeout) & CONNECTED_BIT;
}
