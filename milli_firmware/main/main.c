#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_event.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_psram.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "img_converters.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "camera_manager.h"
#include "capture_policy.h"
#include "face_detection.h"
#include "image_uploader.h"
#include "network_manager.h"

static const char *TAG = "milli";

#define HARDWARE_MODEL "ESP32-S3-N16R8"
#define NETWORK_WAIT_MS 15000
#define REGISTER_RETRY_MS 30000
#define STATUS_PERIOD_MS 60000
#define JPEG_ENCODER_BUF_LEN (128 * 1024)

#if CONFIG_MILLI_UPLOAD_FORMAT_BMP
#define UPLOAD_CONTENT_TYPE "image/bmp"
#else
#define UPLOAD_CONTENT_TYPE "image/jpeg"
#endif

typedef struct {
    uint8_t *data;
    size_t len;
    char capture_id[32];
    time_t captured_at;
    int face_count;
    bool from_policy;  /* the capture policy waits for this job's result */
} upload_job_t;

typedef struct {
    volatile uint32_t frames;
    volatile uint32_t frames_with_faces;
    volatile uint32_t capture_errors;
    volatile uint32_t uploads_accepted;
    volatile uint32_t uploads_failed;
    volatile uint32_t uploads_skipped_offline;
    volatile uint32_t last_detect_ms;
    volatile uint32_t best_score_pct;  /* highest detector score since the last status line */
    volatile bool registered;
} milli_stats_t;

static milli_stats_t s_stats;
static QueueHandle_t s_upload_queue;
static QueueHandle_t s_result_queue;
static camera_info_t s_camera;
static bool s_camera_ok;
static bool s_detector_ok;
static uint32_t s_boot_id;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static void log_boot_banner(void)
{
    const esp_app_desc_t *app = esp_app_get_description();
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    ESP_LOGI(TAG, "Milli firmware %s (%s %s), ESP-IDF %s", app->version, app->date, app->time, esp_get_idf_version());
    ESP_LOGI(TAG, "chip %s rev v%d.%d, %d core(s), flash %" PRIu32 " MB", CONFIG_IDF_TARGET, chip.revision / 100,
             chip.revision % 100, chip.cores, flash_size / (1024 * 1024));
    if (esp_psram_is_initialized()) {
        ESP_LOGI(TAG, "PSRAM %u MB", (unsigned)(esp_psram_get_size() / (1024 * 1024)));
    } else {
        ESP_LOGW(TAG, "PSRAM not detected: camera frame buffers need PSRAM");
    }
    ESP_LOGI(TAG, "free heap: internal %u KB, PSRAM %u KB",
             (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
             (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
}

static void log_config_summary(void)
{
    ESP_LOGI(TAG, "config: device_id=%s server=%s endpoint=%s api_key=%s",
             CONFIG_MILLI_DEVICE_ID[0] ? CONFIG_MILLI_DEVICE_ID : "(not set)",
             CONFIG_MILLI_SERVER_URL[0] ? CONFIG_MILLI_SERVER_URL : "(not set)", CONFIG_MILLI_CAPTURE_ENDPOINT,
             CONFIG_MILLI_DEVICE_API_KEY[0] ? "set" : "(not set)");
#if CONFIG_MILLI_MODE_CAMERA_TEST
    ESP_LOGI(TAG, "mode: camera test (no detection, no upload)");
#else
    ESP_LOGI(TAG, "mode: face detection + upload; format=%s min_score=%d%% confirm=%d absent=%d cooldown=%dms "
                  "min_interval=%dms periodic_upload=%dms",
             UPLOAD_CONTENT_TYPE, CONFIG_MILLI_FACE_MIN_SCORE_PCT, CONFIG_MILLI_FACE_CONFIRM_FRAMES,
             CONFIG_MILLI_FACE_ABSENT_FRAMES, CONFIG_MILLI_CAPTURE_COOLDOWN_MS, CONFIG_MILLI_MIN_UPLOAD_INTERVAL_MS,
             CONFIG_MILLI_PERIODIC_UPLOAD_MS);
#endif
}

static void try_register(void)
{
    device_registration_t device = {
        .firmware_version = esp_app_get_description()->version,
        .hardware_model = HARDWARE_MODEL,
        .camera_model = s_camera_ok ? s_camera.sensor_name : NULL,
        .on_device_face_detection = s_detector_ok,
    };
    upload_result_t result;
    s_stats.registered = image_uploader_register(&device, &result) == ESP_OK;
}

static void upload_task(void *arg)
{
    int64_t next_register_ms = 0;
    for (;;) {
        if (!s_stats.registered && image_uploader_is_configured() && network_manager_is_connected() &&
            now_ms() >= next_register_ms) {
            try_register();
            next_register_ms = now_ms() + REGISTER_RETRY_MS;
        }

        upload_job_t job;
        if (xQueueReceive(s_upload_queue, &job, pdMS_TO_TICKS(1000)) != pdTRUE) {
            continue;
        }

        bool accepted = false;
        if (!network_manager_wait_connected(pdMS_TO_TICKS(NETWORK_WAIT_MS))) {
            ESP_LOGW(TAG, "capture %s dropped: Wi-Fi not connected within %d ms", job.capture_id, NETWORK_WAIT_MS);
        } else {
            image_upload_t upload = {
                .data = job.data,
                .len = job.len,
                .content_type = UPLOAD_CONTENT_TYPE,
                .device_capture_id = job.capture_id,
                .captured_at = job.captured_at,
                .face_count = job.face_count,
                .detector = face_detection_name(),
            };
            upload_result_t result;
            accepted = image_uploader_upload(&upload, &result) == ESP_OK;
            if (accepted) {
                s_stats.registered = true;
                ESP_LOGI(TAG, "capture %s RECEIVED by server as %s (%u bytes, %d face(s) on device)", job.capture_id,
                         result.capture_id, (unsigned)job.len, job.face_count);
            } else {
                ESP_LOGE(TAG, "capture %s NOT received: HTTP %d %s after %d attempt(s)", job.capture_id,
                         result.http_status, result.error_code, result.attempts);
            }
        }
        if (accepted) {
            s_stats.uploads_accepted++;
        } else {
            s_stats.uploads_failed++;
        }
        free(job.data);
        if (job.from_policy) {
            xQueueSend(s_result_queue, &accepted, portMAX_DELAY);
        }
    }
}

#if !CONFIG_MILLI_MODE_CAMERA_TEST
static uint32_t s_capture_seq;

static time_t wall_clock_or_zero(void)
{
    time_t now = time(NULL);
    struct tm tm_utc;
    gmtime_r(&now, &tm_utc);
    return tm_utc.tm_year + 1900 >= 2025 ? now : 0;
}

static bool encode_frame(camera_fb_t *fb, uint8_t **out, size_t *out_len)
{
#if CONFIG_MILLI_UPLOAD_FORMAT_BMP
    return frame2bmp(fb, out, out_len);
#else
    if (!frame2jpg(fb, CONFIG_MILLI_JPEG_QUALITY, out, out_len)) {
        return false;
    }
    const char *problem = NULL;
    if (*out_len >= JPEG_ENCODER_BUF_LEN) {
        problem = "filled the encoder buffer and may be truncated; lower the quality or frame size";
    } else if (*out_len < 4 || (*out)[0] != 0xFF || (*out)[1] != 0xD8) {
        problem = "has no JPEG start marker";
    } else if ((*out)[*out_len - 2] != 0xFF || (*out)[*out_len - 1] != 0xD9) {
        problem = "has no JPEG end marker";
    }
    if (problem != NULL) {
        ESP_LOGE(TAG, "JPEG (%u bytes) %s", (unsigned)*out_len, problem);
        free(*out);
        *out = NULL;
        return false;
    }
    return true;
#endif
}

/* policy is NULL for periodic uploads, which bypass the capture policy. */
static void queue_upload(camera_fb_t *fb, const face_detection_result_t *faces, capture_policy_t *policy)
{
    const char *kind = policy != NULL ? "face detected" : "periodic frame";
    if (!image_uploader_is_configured() || !network_manager_is_connected()) {
        s_stats.uploads_skipped_offline++;
        ESP_LOGW(TAG, "%s, NOT sent to server: %s", kind,
                 image_uploader_is_configured() ? "Wi-Fi not connected" : "backend not configured");
        if (policy != NULL) {
            capture_policy_upload_done(policy, false, now_ms());
        }
        return;
    }

    upload_job_t job = {
        .captured_at = wall_clock_or_zero(),
        .face_count = faces->count,
        .from_policy = policy != NULL,
    };
    snprintf(job.capture_id, sizeof(job.capture_id), "b%08" PRIx32 "-%" PRIu32, s_boot_id, ++s_capture_seq);

    int64_t start = now_ms();
    if (!encode_frame(fb, &job.data, &job.len)) {
        ESP_LOGE(TAG, "capture %s: image encoding failed", job.capture_id);
        if (policy != NULL) {
            capture_policy_upload_done(policy, false, now_ms());
        }
        return;
    }
    ESP_LOGI(TAG, "capture %s (%s): %d face(s) on device, encoded %ux%u to %u bytes %s in %d ms", job.capture_id,
             kind, faces->count, fb->width, fb->height, (unsigned)job.len, UPLOAD_CONTENT_TYPE,
             (int)(now_ms() - start));

    if (xQueueSend(s_upload_queue, &job, 0) != pdTRUE) {
        ESP_LOGW(TAG, "capture %s dropped: upload queue full", job.capture_id);
        free(job.data);
        if (policy != NULL) {
            capture_policy_upload_done(policy, false, now_ms());
        }
    }
}

static void face_task(void *arg)
{
    capture_policy_config_t policy_cfg = {
        .confirm_frames = CONFIG_MILLI_FACE_CONFIRM_FRAMES,
        .absent_frames = CONFIG_MILLI_FACE_ABSENT_FRAMES,
        .cooldown_ms = CONFIG_MILLI_CAPTURE_COOLDOWN_MS,
        .min_interval_ms = CONFIG_MILLI_MIN_UPLOAD_INTERVAL_MS,
    };
    capture_policy_t policy;
    capture_policy_init(&policy, &policy_cfg);
    const float min_score = CONFIG_MILLI_FACE_MIN_SCORE_PCT / 100.0f;
    int last_count = 0;
    int64_t next_periodic_ms = now_ms() + CONFIG_MILLI_PERIODIC_UPLOAD_MS;

    for (;;) {
        bool accepted;
        while (xQueueReceive(s_result_queue, &accepted, 0) == pdTRUE) {
            capture_policy_upload_done(&policy, accepted, now_ms());
        }

        camera_fb_t *fb = camera_manager_capture();
        if (fb == NULL) {
            s_stats.capture_errors++;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        s_stats.frames++;

        face_detection_result_t faces;
        if (face_detection_run(fb->buf, fb->width, fb->height, min_score, &faces) != ESP_OK) {
            camera_manager_release(fb);
            continue;
        }
        s_stats.last_detect_ms = faces.latency_ms;
        uint32_t best_pct = (uint32_t)(faces.best_score * 100.0f + 0.5f);
        if (best_pct > s_stats.best_score_pct) {
            s_stats.best_score_pct = best_pct;
        }
        if (faces.count > 0) {
            s_stats.frames_with_faces++;
        }
        if (faces.count != last_count) {
            if (faces.count > 0) {
                const face_box_t *b = &faces.faces[0];
                ESP_LOGI(TAG, "FACE DETECTED: %d face(s), confidence %d%%, box x=%d y=%d w=%d h=%d, detection %" PRIu32 " ms",
                         faces.count, (int)(b->score * 100.0f + 0.5f), b->x, b->y, b->width, b->height,
                         faces.latency_ms);
            } else {
                ESP_LOGI(TAG, "no face in view");
            }
            last_count = faces.count;
        }

        if (capture_policy_on_frame(&policy, faces.count, now_ms())) {
            queue_upload(fb, &faces, &policy);
            next_periodic_ms = now_ms() + CONFIG_MILLI_PERIODIC_UPLOAD_MS;
        } else if (CONFIG_MILLI_PERIODIC_UPLOAD_MS > 0 && faces.count == 0 && now_ms() >= next_periodic_ms) {
            queue_upload(fb, &faces, NULL);
            next_periodic_ms = now_ms() + CONFIG_MILLI_PERIODIC_UPLOAD_MS;
        }
        camera_manager_release(fb);
    }
}
#else
static void camera_test_task(void *arg)
{
    int64_t window_start = now_ms();
    uint32_t window_frames = 0;
    for (;;) {
        camera_fb_t *fb = camera_manager_capture();
        if (fb == NULL) {
            s_stats.capture_errors++;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        s_stats.frames++;
        window_frames++;

        int64_t elapsed = now_ms() - window_start;
        if (elapsed >= 2000) {
            /* Mean of the green channel over a sparse grid: changes visibly when the lens is covered. */
            uint32_t sum = 0, samples = 0;
            for (size_t i = 0; i + 1 < fb->len; i += 2 * 97) {
                uint16_t px = (uint16_t)(fb->buf[i] << 8 | fb->buf[i + 1]);
                sum += (px >> 5) & 0x3F;
                samples++;
            }
            ESP_LOGI(TAG, "camera test: %ux%u RGB565 %u bytes, %.1f fps, mean green %u/63",
                     fb->width, fb->height, (unsigned)fb->len, window_frames * 1000.0f / (float)elapsed,
                     (unsigned)(samples ? sum / samples : 0));
            window_start = now_ms();
            window_frames = 0;
        }
        camera_manager_release(fb);
    }
}
#endif

static void start_sntp(void)
{
#if CONFIG_MILLI_SNTP_ENABLE
    esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_MILLI_SNTP_SERVER);
    if (esp_netif_sntp_init(&config) != ESP_OK) {
        ESP_LOGW(TAG, "SNTP start failed; uploads will omit X-Captured-At");
    }
#endif
}

void app_main(void)
{
    log_boot_banner();

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS partition needs erasing (%s); erasing NVS only", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    s_boot_id = esp_random();
    log_config_summary();

    bool network_started = network_manager_start(CONFIG_MILLI_WIFI_SSID, CONFIG_MILLI_WIFI_PASSWORD,
                                                 CONFIG_MILLI_WIFI_MAX_BACKOFF_MS) == ESP_OK;
    if (network_started) {
        start_sntp();
    }

    image_uploader_config_t uploader_cfg = {
        .server_url = CONFIG_MILLI_SERVER_URL,
        .device_id = CONFIG_MILLI_DEVICE_ID,
        .api_key = CONFIG_MILLI_DEVICE_API_KEY,
        .capture_endpoint = CONFIG_MILLI_CAPTURE_ENDPOINT,
        .register_endpoint = CONFIG_MILLI_REGISTER_ENDPOINT,
        .timeout_ms = CONFIG_MILLI_HTTP_TIMEOUT_MS,
        .max_attempts = CONFIG_MILLI_UPLOAD_MAX_ATTEMPTS,
        .backoff_ms = CONFIG_MILLI_UPLOAD_BACKOFF_MS,
    };
    if (image_uploader_init(&uploader_cfg) != ESP_OK) {
        ESP_LOGE(TAG, "backend upload disabled until the Milli backend settings are fixed in menuconfig");
    }

    err = camera_manager_init(&s_camera);
    s_camera_ok = err == ESP_OK;
    if (s_camera_ok) {
        ESP_LOGI(TAG, "camera ready: %s PID 0x%04x %ux%u RGB565", s_camera.sensor_name, s_camera.pid, s_camera.width,
                 s_camera.height);
    } else {
        ESP_LOGE(TAG, "BLOCKED: camera not available (%s); network and registration keep running",
                 esp_err_to_name(err));
    }

#if !CONFIG_MILLI_MODE_CAMERA_TEST
    if (s_camera_ok) {
        err = face_detection_init();
        s_detector_ok = err == ESP_OK;
        if (!s_detector_ok) {
            ESP_LOGE(TAG, "BLOCKED: face detector failed to load (%s)", esp_err_to_name(err));
        }
    }
#endif

    s_upload_queue = xQueueCreate(1, sizeof(upload_job_t));
    s_result_queue = xQueueCreate(2, sizeof(bool));
    if (s_upload_queue == NULL || s_result_queue == NULL) {
        ESP_LOGE(TAG, "out of memory creating queues");
        return;
    }
    xTaskCreatePinnedToCore(upload_task, "upload", 8192, NULL, 5, NULL, 0);

#if CONFIG_MILLI_MODE_CAMERA_TEST
    if (s_camera_ok) {
        xTaskCreatePinnedToCore(camera_test_task, "camera_test", 4096, NULL, 4, NULL, 1);
    }
#else
    if (s_camera_ok && s_detector_ok) {
        xTaskCreatePinnedToCore(face_task, "face", 16384, NULL, 4, NULL, 1);
    }
#endif

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(STATUS_PERIOD_MS));
        ESP_LOGI(TAG,
                 "status: wifi=%s registered=%s camera=%s frames=%" PRIu32 " face_frames=%" PRIu32
                 " best_face_score=%" PRIu32 "%% (need %d%%) detect=%" PRIu32 "ms uploads ok=%" PRIu32
                 " failed=%" PRIu32 " offline=%" PRIu32 " capture_errors=%" PRIu32 " heap internal=%uKB psram=%uKB",
                 network_manager_is_connected() ? "up" : "down", s_stats.registered ? "yes" : "no",
                 s_camera_ok ? "ok" : "BLOCKED", s_stats.frames, s_stats.frames_with_faces, s_stats.best_score_pct,
                 CONFIG_MILLI_FACE_MIN_SCORE_PCT, s_stats.last_detect_ms, s_stats.uploads_accepted,
                 s_stats.uploads_failed, s_stats.uploads_skipped_offline, s_stats.capture_errors,
                 (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
                 (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
        s_stats.best_score_pct = 0;
    }
}
