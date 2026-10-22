#include "image_encoder.h"

#include <cstring>

#include "dl_image_jpeg.hpp"
#include "esp_heap_caps.h"
#include "esp_log.h"

static const char *TAG = "encoder";

static void *alloc_large(size_t size)
{
    void *p = heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    return p ? p : heap_caps_malloc(size, MALLOC_CAP_8BIT);
}

static void put_le16(uint8_t *p, uint16_t v)
{
    p[0] = v & 0xff;
    p[1] = v >> 8;
}

static void put_le32(uint8_t *p, uint32_t v)
{
    for (int i = 0; i < 4; i++) {
        p[i] = (v >> (8 * i)) & 0xff;
    }
}

static esp_err_t encode_bmp(const uint8_t *rgb565, int width, int height, bool little_endian, encoded_image_t *out)
{
    const size_t header = 54;
    const size_t row = ((size_t)width * 3 + 3) & ~(size_t)3;
    const size_t total = header + row * height;
    uint8_t *buf = static_cast<uint8_t *>(alloc_large(total));
    if (buf == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    memset(buf, 0, header);
    buf[0] = 'B';
    buf[1] = 'M';
    put_le32(buf + 2, total);
    put_le32(buf + 10, header);
    put_le32(buf + 14, 40);
    put_le32(buf + 18, width);
    put_le32(buf + 22, height);
    put_le16(buf + 26, 1);
    put_le16(buf + 28, 24);
    put_le32(buf + 34, row * height);

    for (int y = 0; y < height; y++) {
        const uint8_t *src = rgb565 + (size_t)y * width * 2;
        uint8_t *dst = buf + header + (size_t)(height - 1 - y) * row; /* BMP rows are bottom-up */
        for (int x = 0; x < width; x++) {
            uint16_t px = little_endian ? (src[1] << 8 | src[0]) : (src[0] << 8 | src[1]);
            src += 2;
            uint8_t r = (px >> 11) & 0x1f, g = (px >> 5) & 0x3f, b = px & 0x1f;
            *dst++ = (b << 3) | (b >> 2);
            *dst++ = (g << 2) | (g >> 4);
            *dst++ = (r << 3) | (r >> 2);
        }
        memset(dst, 0, row - (size_t)width * 3);
    }
    out->data = buf;
    out->len = total;
    out->content_type = "image/bmp";
    return ESP_OK;
}

static esp_err_t encode_jpeg(const uint8_t *rgb565, int width, int height, bool little_endian, int quality,
                             encoded_image_t *out)
{
    dl::image::img_t img = {
        .data = const_cast<uint8_t *>(rgb565),
        .width = static_cast<uint16_t>(width),
        .height = static_cast<uint16_t>(height),
        .pix_type = little_endian ? dl::image::DL_IMAGE_PIX_TYPE_RGB565LE : dl::image::DL_IMAGE_PIX_TYPE_RGB565BE,
    };
    dl::image::jpeg_img_t jpeg = dl::image::sw_encode_jpeg(img, static_cast<uint8_t>(quality));
    if (jpeg.data == nullptr || jpeg.data_len == 0) {
        free(jpeg.data);
        return ESP_FAIL;
    }
    out->data = static_cast<uint8_t *>(jpeg.data);
    out->len = jpeg.data_len;
    out->content_type = "image/jpeg";
    return ESP_OK;
}

esp_err_t image_encoder_encode(const uint8_t *rgb565, int width, int height, bool little_endian,
                               image_format_t format, int jpeg_quality, encoded_image_t *out)
{
    if (rgb565 == nullptr || out == nullptr || width <= 0 || height <= 0) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = {};
    esp_err_t err = (format == IMAGE_FORMAT_BMP) ? encode_bmp(rgb565, width, height, little_endian, out)
                                                 : encode_jpeg(rgb565, width, height, little_endian, jpeg_quality, out);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "%s encoding of %dx%d frame failed: %s", format == IMAGE_FORMAT_BMP ? "BMP" : "JPEG", width,
                 height, esp_err_to_name(err));
    }
    return err;
}
