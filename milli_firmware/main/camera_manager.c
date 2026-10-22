#include "camera_manager.h"

#include <string.h>
#include "esp_log.h"
#include "esp_psram.h"
#include "sdkconfig.h"

static const char *TAG = "camera";

#define GC2145_PID 0x2145

typedef struct {
    const char *name;
    int gpio;
    bool required;
} pin_t;

static bool s_ready;

static esp_err_t validate_pins(const pin_t *pins, size_t count)
{
    bool ok = true;
    for (size_t i = 0; i < count; i++) {
        int gpio = pins[i].gpio;
        if (gpio < 0) {
            if (pins[i].required) {
                ESP_LOGE(TAG, "pin %s is not configured", pins[i].name);
                ok = false;
            }
            continue;
        }
        // GPIO26-32 connect the module's flash; on octal-PSRAM modules (N16R8) GPIO33-37 are used too.
        if (gpio >= 26 && gpio <= 37) {
            ESP_LOGE(TAG, "pin %s=GPIO%d is used by flash/octal PSRAM on N16R8 modules", pins[i].name, gpio);
            ok = false;
        }
        if (gpio == 19 || gpio == 20) {
            ESP_LOGW(TAG, "pin %s=GPIO%d is a USB D-/D+ pin; native USB will not work", pins[i].name, gpio);
        }
        for (size_t j = i + 1; j < count; j++) {
            if (pins[j].gpio == gpio) {
                ESP_LOGE(TAG, "pins %s and %s both use GPIO%d", pins[i].name, pins[j].name, gpio);
                ok = false;
            }
        }
    }
    return ok ? ESP_OK : ESP_ERR_INVALID_ARG;
}

esp_err_t camera_manager_init(camera_info_t *info)
{
#if !CONFIG_MILLI_CAM_PINS_VERIFIED
    ESP_LOGE(TAG, "camera disabled: pins are not verified. Set them in idf.py menuconfig -> "
                  "Milli configuration -> Camera pins, then enable 'I have verified these pins'");
    return ESP_ERR_INVALID_STATE;
#endif
    const pin_t pins[] = {
        {"PWDN", CONFIG_MILLI_CAM_PIN_PWDN, false},   {"RESET", CONFIG_MILLI_CAM_PIN_RESET, false},
        {"XCLK", CONFIG_MILLI_CAM_PIN_XCLK, false},   {"SIOD", CONFIG_MILLI_CAM_PIN_SIOD, true},
        {"SIOC", CONFIG_MILLI_CAM_PIN_SIOC, true},    {"D7", CONFIG_MILLI_CAM_PIN_D7, true},
        {"D6", CONFIG_MILLI_CAM_PIN_D6, true},        {"D5", CONFIG_MILLI_CAM_PIN_D5, true},
        {"D4", CONFIG_MILLI_CAM_PIN_D4, true},        {"D3", CONFIG_MILLI_CAM_PIN_D3, true},
        {"D2", CONFIG_MILLI_CAM_PIN_D2, true},        {"D1", CONFIG_MILLI_CAM_PIN_D1, true},
        {"D0", CONFIG_MILLI_CAM_PIN_D0, true},        {"VSYNC", CONFIG_MILLI_CAM_PIN_VSYNC, true},
        {"HREF", CONFIG_MILLI_CAM_PIN_HREF, true},    {"PCLK", CONFIG_MILLI_CAM_PIN_PCLK, true},
    };
    esp_err_t err = validate_pins(pins, sizeof(pins) / sizeof(pins[0]));
    if (err != ESP_OK) {
        return err;
    }
    if (!esp_psram_is_initialized()) {
        ESP_LOGE(TAG, "PSRAM is not available; frame buffers need PSRAM");
        return ESP_ERR_NO_MEM;
    }

    camera_config_t config = {
        .pin_pwdn = CONFIG_MILLI_CAM_PIN_PWDN,
        .pin_reset = CONFIG_MILLI_CAM_PIN_RESET,
        .pin_xclk = CONFIG_MILLI_CAM_PIN_XCLK,
        .pin_sccb_sda = CONFIG_MILLI_CAM_PIN_SIOD,
        .pin_sccb_scl = CONFIG_MILLI_CAM_PIN_SIOC,
        .pin_d7 = CONFIG_MILLI_CAM_PIN_D7,
        .pin_d6 = CONFIG_MILLI_CAM_PIN_D6,
        .pin_d5 = CONFIG_MILLI_CAM_PIN_D5,
        .pin_d4 = CONFIG_MILLI_CAM_PIN_D4,
        .pin_d3 = CONFIG_MILLI_CAM_PIN_D3,
        .pin_d2 = CONFIG_MILLI_CAM_PIN_D2,
        .pin_d1 = CONFIG_MILLI_CAM_PIN_D1,
        .pin_d0 = CONFIG_MILLI_CAM_PIN_D0,
        .pin_vsync = CONFIG_MILLI_CAM_PIN_VSYNC,
        .pin_href = CONFIG_MILLI_CAM_PIN_HREF,
        .pin_pclk = CONFIG_MILLI_CAM_PIN_PCLK,
        .xclk_freq_hz = CONFIG_MILLI_CAM_XCLK_FREQ_HZ,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_RGB565,
#if CONFIG_MILLI_CAM_FRAME_VGA
        .frame_size = FRAMESIZE_VGA,
#else
        .frame_size = FRAMESIZE_QVGA,
#endif
        .jpeg_quality = 12,
        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST,
    };

    ESP_LOGI(TAG, "initializing camera (XCLK %d Hz, RGB565, %s)", config.xclk_freq_hz,
             config.frame_size == FRAMESIZE_VGA ? "VGA 640x480" : "QVGA 320x240");
    err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init failed: %s (0x%x). No sensor answered on SCCB or setup failed; "
                      "check pins, power and the ribbon cable", esp_err_to_name(err), err);
        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL) {
        esp_camera_deinit();
        return ESP_FAIL;
    }
    camera_sensor_info_t *sensor_info = esp_camera_sensor_get_info(&sensor->id);
    const char *name = sensor_info ? sensor_info->name : "unknown";
    ESP_LOGI(TAG, "sensor detected: %s (PID 0x%04x)", name, sensor->id.PID);
    if (sensor->id.PID != GC2145_PID) {
        ESP_LOGE(TAG, "expected GC2145 (PID 0x2145) but found %s; refusing to continue", name);
        esp_camera_deinit();
        return ESP_ERR_NOT_SUPPORTED;
    }

#if CONFIG_MILLI_CAM_HMIRROR
    const int hmirror = 1;
#else
    const int hmirror = 0;
#endif
#if CONFIG_MILLI_CAM_VFLIP
    const int vflip = 1;
#else
    const int vflip = 0;
#endif
    if (sensor->set_hmirror) {
        sensor->set_hmirror(sensor, hmirror);
    }
    if (sensor->set_vflip) {
        sensor->set_vflip(sensor, vflip);
    }

    if (info != NULL) {
        memset(info, 0, sizeof(*info));
        strlcpy(info->sensor_name, name, sizeof(info->sensor_name));
        info->pid = sensor->id.PID;
        info->width = config.frame_size == FRAMESIZE_VGA ? 640 : 320;
        info->height = config.frame_size == FRAMESIZE_VGA ? 480 : 240;
    }
    s_ready = true;
    return ESP_OK;
}

camera_fb_t *camera_manager_capture(void)
{
    if (!s_ready) {
        return NULL;
    }
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb == NULL) {
        ESP_LOGW(TAG, "frame capture timed out");
        return NULL;
    }
    size_t expected = fb->width * fb->height * 2;
    if (fb->format != PIXFORMAT_RGB565 || fb->len != expected) {
        ESP_LOGW(TAG, "discarding malformed frame: format=%d len=%u expected=%u (%ux%u)", fb->format,
                 (unsigned)fb->len, (unsigned)expected, (unsigned)fb->width, (unsigned)fb->height);
        esp_camera_fb_return(fb);
        return NULL;
    }
    return fb;
}

void camera_manager_release(camera_fb_t *fb)
{
    if (fb != NULL) {
        esp_camera_fb_return(fb);
    }
}
