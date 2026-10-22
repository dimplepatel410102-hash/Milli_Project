#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_camera.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char sensor_name[16];
    uint16_t pid;
    uint16_t width;
    uint16_t height;
} camera_info_t;

/**
 * Validate the configured pins, initialize esp32-camera in RGB565 mode with
 * PSRAM frame buffers and confirm the sensor is a GC2145.
 *
 * ESP_ERR_INVALID_STATE: pins not marked as verified in menuconfig.
 * ESP_ERR_INVALID_ARG:   pin configuration is incomplete or conflicting.
 * ESP_ERR_NOT_SUPPORTED: a sensor answered but it is not a GC2145.
 */
esp_err_t camera_manager_init(camera_info_t *info);

/** Get a validated RGB565 frame, or NULL on timeout/error. Release with camera_manager_release(). */
camera_fb_t *camera_manager_capture(void);

void camera_manager_release(camera_fb_t *fb);

#ifdef __cplusplus
}
#endif
