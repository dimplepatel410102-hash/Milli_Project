#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *server_url;         /* e.g. http://192.168.1.50:8000 */
    const char *device_id;
    const char *api_key;            /* sent as X-Device-Key, never logged */
    const char *capture_endpoint;   /* /api/v1/camera/capture */
    const char *register_endpoint;  /* /api/v1/devices/register */
    int timeout_ms;
    int max_attempts;
    int backoff_ms;
} image_uploader_config_t;

typedef struct {
    const char *firmware_version;
    const char *hardware_model;
    const char *camera_model;       /* NULL if the camera is not running */
    bool on_device_face_detection;
} device_registration_t;

typedef struct {
    const uint8_t *data;
    size_t len;
    const char *content_type;       /* matches the encoded bytes, e.g. image/jpeg */
    const char *device_capture_id;  /* X-Capture-Id */
    time_t captured_at;             /* 0 if wall-clock time is not synced */
    int face_count;                 /* < 0: do not report device detection */
    const char *detector;           /* X-Device-Detector */
} image_upload_t;

typedef struct {
    int http_status;                /* 0 if no HTTP response was received */
    int attempts;
    bool accepted;                  /* server confirmed receipt (200 + status "received") */
    char capture_id[48];            /* server-assigned capture_id */
    char error_code[40];            /* server error.code, or a local reason */
} upload_result_t;

/** Copy and validate the configuration. Returns ESP_ERR_INVALID_ARG if anything required is missing. */
esp_err_t image_uploader_init(const image_uploader_config_t *config);

bool image_uploader_is_configured(void);

esp_err_t image_uploader_register(const device_registration_t *device, upload_result_t *result);

/** POST the image bytes; retries transient failures. ESP_OK only when the server accepted the image. */
esp_err_t image_uploader_upload(const image_upload_t *upload, upload_result_t *result);

#ifdef __cplusplus
}
#endif
