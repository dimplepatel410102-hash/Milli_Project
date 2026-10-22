/*
 * Emulator test for the firmware's capture policy, image encoders and uploader.
 * Runs in QEMU (esp32s3 + open_eth) against the real Phase 1 backend on the host.
 * The uploaded frame is a synthetic colour-bar test pattern, reported as 0 faces.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_eth.h"
#include "esp_eth_mac_openeth.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "img_converters.h"
#include "sdkconfig.h"

#include "capture_policy.h"
#include "image_uploader.h"

static const char *TAG = "qemu_test";

static int s_pass;
static int s_fail;

#define CHECK(name, cond)                                   \
    do {                                                    \
        if (cond) {                                         \
            s_pass++;                                       \
            printf("TEST PASS: %s\n", name);                \
        } else {                                            \
            s_fail++;                                       \
            printf("TEST FAIL: %s  (%s)\n", name, #cond);   \
        }                                                   \
    } while (0)

/* ---------------------------------------------------------------- capture policy */

static void test_capture_policy(void)
{
    const capture_policy_config_t cfg = {
        .confirm_frames = 2, .absent_frames = 3, .cooldown_ms = 30000, .min_interval_ms = 5000,
    };
    capture_policy_t p;

    capture_policy_init(&p, &cfg);
    CHECK("policy: empty frames never upload", !capture_policy_on_frame(&p, 0, 0) && !capture_policy_on_frame(&p, 0, 10));
    CHECK("policy: single face frame is not enough", !capture_policy_on_frame(&p, 1, 100));
    CHECK("policy: second consecutive face frame uploads", capture_policy_on_frame(&p, 1, 200));
    CHECK("policy: no second upload while one is in flight", !capture_policy_on_frame(&p, 1, 300));
    capture_policy_upload_done(&p, true, 1000);
    CHECK("policy: same person suppressed before cooldown", !capture_policy_on_frame(&p, 1, 20000));
    CHECK("policy: same person re-uploaded after cooldown", capture_policy_on_frame(&p, 1, 31000));
    capture_policy_upload_done(&p, true, 31000);

    /* Person leaves, a new one arrives 2 s later: min interval still applies. */
    for (int i = 0; i < 3; i++) {
        capture_policy_on_frame(&p, 0, 32000 + i);
    }
    CHECK("policy: absence detected after absent_frames", !p.present);
    capture_policy_on_frame(&p, 1, 33000);
    CHECK("policy: new person blocked by min interval", !capture_policy_on_frame(&p, 1, 33100));
    CHECK("policy: new person uploaded after min interval", capture_policy_on_frame(&p, 1, 36100));

    /* Failed upload: the same presence is retried, but not faster than min interval. */
    capture_policy_upload_done(&p, false, 36500);
    CHECK("policy: retry after failure waits for min interval", !capture_policy_on_frame(&p, 1, 37000));
    CHECK("policy: retry after failure allowed", capture_policy_on_frame(&p, 1, 41600));
    capture_policy_upload_done(&p, true, 41600);

    /* Brief dropout shorter than absent_frames does not count as a new person. */
    capture_policy_on_frame(&p, 0, 42000);
    capture_policy_on_frame(&p, 0, 42100);
    CHECK("policy: short dropout keeps presence", p.present);
    CHECK("policy: no duplicate after short dropout", !capture_policy_on_frame(&p, 1, 50000));

    /* Cooldown 0: one upload per presence. */
    const capture_policy_config_t once = {.confirm_frames = 1, .absent_frames = 1, .cooldown_ms = 0, .min_interval_ms = 0};
    capture_policy_init(&p, &once);
    CHECK("policy(cooldown=0): first upload", capture_policy_on_frame(&p, 2, 0));
    capture_policy_upload_done(&p, true, 10);
    CHECK("policy(cooldown=0): never again while present", !capture_policy_on_frame(&p, 2, 3600000));
    capture_policy_on_frame(&p, 0, 3600001);
    CHECK("policy(cooldown=0): uploads again for next presence", capture_policy_on_frame(&p, 1, 3600002));

    /* Person changes while the upload is in flight: the new person is not marked captured. */
    capture_policy_on_frame(&p, 0, 3700000);
    capture_policy_on_frame(&p, 1, 3700001);
    capture_policy_upload_done(&p, true, 3700002);
    CHECK("policy: success for a previous presence does not suppress the new one",
          capture_policy_on_frame(&p, 1, 3700003));
}

/* ---------------------------------------------------------------- encoders */

#define TEST_W 320
#define TEST_H 240

static uint8_t *make_color_bars(void)
{
    static const uint16_t bars[8] = {0xFFFF, 0xFFE0, 0x07FF, 0x07E0, 0xF81F, 0xF800, 0x001F, 0x0000};
    uint8_t *buf = heap_caps_malloc(TEST_W * TEST_H * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (buf == NULL) {
        buf = malloc(TEST_W * TEST_H * 2);
    }
    if (buf == NULL) {
        return NULL;
    }
    for (int y = 0; y < TEST_H; y++) {
        for (int x = 0; x < TEST_W; x++) {
            uint16_t px = bars[x * 8 / TEST_W];
            buf[(y * TEST_W + x) * 2] = px >> 8; /* big-endian, as esp32-camera delivers RGB565 */
            buf[(y * TEST_W + x) * 2 + 1] = px & 0xFF;
        }
    }
    return buf;
}

/* ---------------------------------------------------------------- network */

#define GOT_IP_BIT BIT0
static EventGroupHandle_t s_net_events;

static void on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    ip_event_got_ip_t *event = data;
    ESP_LOGI(TAG, "got IP " IPSTR, IP2STR(&event->ip_info.ip));
    xEventGroupSetBits(s_net_events, GOT_IP_BIT);
}

static bool start_openeth(void)
{
    s_net_events = xEventGroupCreate();
    esp_netif_config_t netif_cfg = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&netif_cfg);

    eth_mac_config_t mac_cfg = ETH_MAC_DEFAULT_CONFIG();
    eth_phy_config_t phy_cfg = ETH_PHY_DEFAULT_CONFIG();
    phy_cfg.autonego_timeout_ms = 100;
    esp_eth_mac_t *mac = esp_eth_mac_new_openeth(&mac_cfg);
    esp_eth_phy_t *phy = esp_eth_phy_new_generic(&phy_cfg);
    esp_eth_config_t eth_cfg = ETH_DEFAULT_CONFIG(mac, phy);
    esp_eth_handle_t eth = NULL;
    if (esp_eth_driver_install(&eth_cfg, &eth) != ESP_OK) {
        return false;
    }
    esp_netif_attach(netif, esp_eth_new_netif_glue(eth));
    esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP, on_got_ip, NULL);
    if (esp_eth_start(eth) != ESP_OK) {
        return false;
    }
    return xEventGroupWaitBits(s_net_events, GOT_IP_BIT, pdFALSE, pdTRUE, pdMS_TO_TICKS(30000)) & GOT_IP_BIT;
}

/* ---------------------------------------------------------------- uploader */

static image_uploader_config_t uploader_config(const char *url, const char *key)
{
    image_uploader_config_t cfg = {
        .server_url = url,
        .device_id = CONFIG_TEST_DEVICE_ID,
        .api_key = key,
        .capture_endpoint = "/api/v1/camera/capture",
        .register_endpoint = "/api/v1/devices/register",
        .timeout_ms = 10000,
        .max_attempts = 3,
        .backoff_ms = 500,
    };
    return cfg;
}

static void test_uploads(const uint8_t *jpg, size_t jpg_len, const uint8_t *bmp, size_t bmp_len)
{
    upload_result_t r;
    image_uploader_config_t cfg = uploader_config(CONFIG_TEST_SERVER_URL, CONFIG_TEST_DEVICE_API_KEY);
    CHECK("uploader: init with test config", image_uploader_init(&cfg) == ESP_OK);

    image_upload_t jpeg_upload = {
        .data = jpg, .len = jpg_len, .content_type = "image/jpeg", .device_capture_id = "qemu-jpeg-1",
        .captured_at = 1767225600, /* fixed test timestamp, 2026-01-01T00:00:00Z */
        .face_count = 0, .detector = "test-pattern",
    };

    /* The backend under test runs with MILLI_REQUIRE_REGISTRATION=true. */
    esp_err_t err = image_uploader_upload(&jpeg_upload, &r);
    CHECK("upload before registration is rejected", err != ESP_OK && !r.accepted);
    CHECK("  ... with HTTP 403 device_not_registered", r.http_status == 403 &&
          strcmp(r.error_code, "device_not_registered") == 0);
    CHECK("  ... and is not retried", r.attempts == 1);

    device_registration_t device = {
        .firmware_version = "0.1.0-qemu", .hardware_model = "QEMU-ESP32-S3", .camera_model = NULL,
        .on_device_face_detection = false,
    };
    err = image_uploader_register(&device, &r);
    CHECK("registration accepted (HTTP 200)", err == ESP_OK && r.accepted && r.http_status == 200);

    err = image_uploader_upload(&jpeg_upload, &r);
    CHECK("JPEG upload confirmed by server", err == ESP_OK && r.accepted && r.http_status == 200);
    CHECK("  ... server returned a capture_id", r.capture_id[0] != '\0');
    printf("JPEG capture_id=%s bytes=%u attempts=%d\n", r.capture_id, (unsigned)jpg_len, r.attempts);

    image_upload_t bmp_upload = {
        .data = bmp, .len = bmp_len, .content_type = "image/bmp", .device_capture_id = "qemu-bmp-1",
        .captured_at = 0, .face_count = -1, .detector = NULL,
    };
    err = image_uploader_upload(&bmp_upload, &r);
    CHECK("BMP upload confirmed by server", err == ESP_OK && r.accepted && r.capture_id[0] != '\0');
    printf("BMP capture_id=%s bytes=%u attempts=%d\n", r.capture_id, (unsigned)bmp_len, r.attempts);

    static const uint8_t garbage[64] = "this is not an image, just bytes for a negative test.......";
    image_upload_t bad_upload = {
        .data = garbage, .len = sizeof(garbage), .content_type = "image/jpeg", .device_capture_id = "qemu-bad-1",
        .face_count = -1,
    };
    err = image_uploader_upload(&bad_upload, &r);
    CHECK("non-image bytes rejected, not reported as success", err != ESP_OK && !r.accepted);
    CHECK("  ... with HTTP 415/422 and no retry", (r.http_status == 415 || r.http_status == 422) && r.attempts == 1);
    printf("non-image upload: HTTP %d %s\n", r.http_status, r.error_code);

    cfg = uploader_config(CONFIG_TEST_SERVER_URL, "wrong-key-for-negative-test");
    image_uploader_init(&cfg);
    err = image_uploader_upload(&jpeg_upload, &r);
    CHECK("wrong API key rejected with HTTP 401, no retry",
          err != ESP_OK && !r.accepted && r.http_status == 401 && r.attempts == 1);

    cfg = uploader_config(CONFIG_TEST_UNREACHABLE_URL, CONFIG_TEST_DEVICE_API_KEY);
    cfg.timeout_ms = 3000;
    image_uploader_init(&cfg);
    int64_t start = esp_timer_get_time();
    err = image_uploader_upload(&jpeg_upload, &r);
    int elapsed_ms = (int)((esp_timer_get_time() - start) / 1000);
    CHECK("unreachable server: upload fails, not reported as success", err != ESP_OK && !r.accepted);
    CHECK("  ... after exactly max_attempts (3) tries", r.attempts == 3 && r.http_status == 0);
    CHECK("  ... with backoff between tries (>= 500+1000 ms)", elapsed_ms >= 1500);
    printf("unreachable server: %d attempts in %d ms, error=%s\n", r.attempts, elapsed_ms, r.error_code);

    cfg = uploader_config("ftp://10.0.2.2", CONFIG_TEST_DEVICE_API_KEY);
    CHECK("config: non-HTTP URL rejected", image_uploader_init(&cfg) == ESP_ERR_INVALID_ARG);
    cfg = uploader_config(CONFIG_TEST_SERVER_URL, "");
    CHECK("config: empty API key rejected", image_uploader_init(&cfg) == ESP_ERR_INVALID_ARG);
}

void app_main(void)
{
    printf("=== Milli QEMU upload test (emulator, synthetic test pattern; not a hardware test) ===\n");
    /* No nvs_flash_init(): QEMU's 32 MB PSRAM uses the whole MMU range, so partition mmap fails. */
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    test_capture_policy();

    uint8_t *frame = make_color_bars();
    uint8_t *jpg = NULL, *bmp = NULL;
    size_t jpg_len = 0, bmp_len = 0;
    CHECK("encoder: test frame allocated", frame != NULL);
    if (frame != NULL) {
        bool ok = fmt2jpg(frame, TEST_W * TEST_H * 2, TEST_W, TEST_H, PIXFORMAT_RGB565, 80, &jpg, &jpg_len);
        CHECK("encoder: RGB565 -> JPEG", ok && jpg_len > 4 && jpg[0] == 0xFF && jpg[1] == 0xD8 &&
              jpg[jpg_len - 2] == 0xFF && jpg[jpg_len - 1] == 0xD9 && jpg_len < 128 * 1024);
        ok = fmt2bmp(frame, TEST_W * TEST_H * 2, TEST_W, TEST_H, PIXFORMAT_RGB565, &bmp, &bmp_len);
        CHECK("encoder: RGB565 -> BMP", ok && bmp[0] == 'B' && bmp[1] == 'M' && bmp_len == 54 + TEST_W * TEST_H * 3);
        printf("encoded %dx%d: JPEG %u bytes, BMP %u bytes\n", TEST_W, TEST_H, (unsigned)jpg_len, (unsigned)bmp_len);
    }

    bool net = start_openeth();
    CHECK("network: QEMU open_eth got an IP via DHCP", net);
    if (net && jpg != NULL && bmp != NULL) {
        if (CONFIG_TEST_DEVICE_ID[0] == '\0' || CONFIG_TEST_DEVICE_API_KEY[0] == '\0') {
            printf("TEST FAIL: TEST_DEVICE_ID / TEST_DEVICE_API_KEY not configured\n");
            s_fail++;
        } else {
            test_uploads(jpg, jpg_len, bmp, bmp_len);
        }
    }

    free(jpg);
    free(bmp);
    free(frame);
    printf("=== RESULT: %d passed, %d failed ===\n", s_pass, s_fail);
}
