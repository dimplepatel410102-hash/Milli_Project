#pragma once

#include <stdint.h>
#include "esp_err.h"


#ifdef __cplusplus
extern "C" {
#endif

#define FACE_DETECTION_MAX_FACES 8

typedef struct {
    int x;
    int y;
    int width;
    int height;
    float score;
} face_box_t;

typedef struct {
    int count;                                   /* faces at or above the score threshold */
    face_box_t faces[FACE_DETECTION_MAX_FACES];
    float best_score;                            /* highest candidate score, including rejected ones */
    uint32_t latency_ms;
} face_detection_result_t;

/** Load the ESP-DL human_face_detect model (MSR+MNP s8 v1). */
esp_err_t face_detection_init(void);

/**
 * Run detection on a big-endian RGB565 frame (esp32-camera byte order).
 * Faces below min_score (0..1) are dropped.
 */
esp_err_t face_detection_run(const uint8_t *rgb565_be, uint16_t width, uint16_t height, float min_score,
                             face_detection_result_t *result);

/** Detector name reported to the backend (X-Device-Detector). */
const char *face_detection_name(void);

#ifdef __cplusplus
}
#endif
