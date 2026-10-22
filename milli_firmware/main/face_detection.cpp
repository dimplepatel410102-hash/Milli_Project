// C++ because ESP-DL's human_face_detect API is C++ only; callers use the C header.
#include "face_detection.h"

#include <string.h>
#include <new>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "human_face_detect.hpp"
#include "sdkconfig.h"

#if !CONFIG_FLASH_HUMAN_FACE_DETECT_MSRMNP_S8_V1 || !CONFIG_HUMAN_FACE_DETECT_MODEL_IN_FLASH_RODATA
#error "Enable the MSR+MNP s8 v1 face model in flash rodata (see sdkconfig.defaults)"
#endif

static const char *TAG = "face_detect";

static HumanFaceDetect *s_detector;

extern "C" esp_err_t face_detection_init(void)
{
    if (s_detector != nullptr) {
        return ESP_OK;
    }
    size_t before = heap_caps_get_free_size(MALLOC_CAP_DEFAULT);
    s_detector = new (std::nothrow) HumanFaceDetect(HumanFaceDetect::MSRMNP_S8_V1, false);
    if (s_detector == nullptr) {
        ESP_LOGE(TAG, "out of memory creating the face detector");
        return ESP_ERR_NO_MEM;
    }
    size_t after = heap_caps_get_free_size(MALLOC_CAP_DEFAULT);
    ESP_LOGI(TAG, "ESP-DL face detector loaded (%s), model memory ~%u KB", face_detection_name(),
             (unsigned)((before > after ? before - after : 0) / 1024));
    return ESP_OK;
}

extern "C" esp_err_t face_detection_run(const uint8_t *rgb565_be, uint16_t width, uint16_t height,
                                        float min_score, face_detection_result_t *result)
{
    if (s_detector == nullptr || rgb565_be == nullptr || result == nullptr || width == 0 || height == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(result, 0, sizeof(*result));

    dl::image::img_t img = {
        .data = const_cast<uint8_t *>(rgb565_be),
        .width = width,
        .height = height,
        .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565BE,
    };

    int64_t start = esp_timer_get_time();
    std::list<dl::detect::result_t> &detections = s_detector->run(img);
    result->latency_ms = (uint32_t)((esp_timer_get_time() - start) / 1000);

    for (const auto &det : detections) {
        if (det.score > result->best_score) {
            result->best_score = det.score;
        }
        if (det.score < min_score || det.box.size() < 4) {
            continue;
        }
        if (result->count >= FACE_DETECTION_MAX_FACES) {
            continue;
        }
        face_box_t &box = result->faces[result->count++];
        box.x = det.box[0];
        box.y = det.box[1];
        box.width = det.box[2] - det.box[0];
        box.height = det.box[3] - det.box[1];
        box.score = det.score;
    }
    return ESP_OK;
}

extern "C" const char *face_detection_name(void)
{
    return "esp-dl-msrmnp-s8-v1";
}
