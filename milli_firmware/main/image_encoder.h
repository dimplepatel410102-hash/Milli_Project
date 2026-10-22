#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    IMAGE_FORMAT_JPEG,
    IMAGE_FORMAT_BMP,
} image_format_t;

typedef struct {
    uint8_t *data; /* heap buffer, release with free() */
    size_t len;
    const char *content_type;
} encoded_image_t;

/* Encodes an RGB565 frame for upload. The backend accepts JPEG/PNG/BMP/WEBP, not raw RGB565. */
esp_err_t image_encoder_encode(const uint8_t *rgb565, int width, int height, bool little_endian,
                               image_format_t format, int jpeg_quality, encoded_image_t *out);

#ifdef __cplusplus
}
#endif
