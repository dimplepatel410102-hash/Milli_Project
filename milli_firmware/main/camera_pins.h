#pragma once

#include "sdkconfig.h"

/*
 * Preset pin maps are copied verbatim from espressif/esp32-camera 2.1.8,
 * examples/camera_example/main/camera_pinout.h. They describe the board's
 * 24-pin DVP camera connector, so they apply to any DVP sensor fitted to it
 * (OV2640, GC2145, ...). Select one only after checking your board schematic.
 */

#define CAMERA_PINS_CONFIGURED 1

#if CONFIG_MILLI_CAMERA_PINOUT_ESP32S3_WROOM
#define CAMERA_PINS_NAME "esp32-camera BOARD_ESP32S3_WROOM"
#define CAM_PIN_PWDN 38
#define CAM_PIN_RESET -1
#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF 7
#define CAM_PIN_PCLK 13
#define CAM_PIN_XCLK 15
#define CAM_PIN_SIOD 4
#define CAM_PIN_SIOC 5
#define CAM_PIN_D0 11
#define CAM_PIN_D1 9
#define CAM_PIN_D2 8
#define CAM_PIN_D3 10
#define CAM_PIN_D4 12
#define CAM_PIN_D5 18
#define CAM_PIN_D6 17
#define CAM_PIN_D7 16

#elif CONFIG_MILLI_CAMERA_PINOUT_ESP32S3_GOOUUU
#define CAMERA_PINS_NAME "esp32-camera BOARD_ESP32S3_GOOUUU"
#define CAM_PIN_PWDN -1
#define CAM_PIN_RESET -1
#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF 7
#define CAM_PIN_PCLK 13
#define CAM_PIN_XCLK 15
#define CAM_PIN_SIOD 4
#define CAM_PIN_SIOC 5
#define CAM_PIN_D0 11
#define CAM_PIN_D1 9
#define CAM_PIN_D2 8
#define CAM_PIN_D3 10
#define CAM_PIN_D4 12
#define CAM_PIN_D5 18
#define CAM_PIN_D6 17
#define CAM_PIN_D7 16

#elif CONFIG_MILLI_CAMERA_PINOUT_ESP32S3_XIAO
#define CAMERA_PINS_NAME "esp32-camera BOARD_ESP32S3_XIAO"
#define CAM_PIN_PWDN -1
#define CAM_PIN_RESET -1
#define CAM_PIN_VSYNC 38
#define CAM_PIN_HREF 47
#define CAM_PIN_PCLK 13
#define CAM_PIN_XCLK 10
#define CAM_PIN_SIOD 40
#define CAM_PIN_SIOC 39
#define CAM_PIN_D0 15
#define CAM_PIN_D1 17
#define CAM_PIN_D2 18
#define CAM_PIN_D3 16
#define CAM_PIN_D4 14
#define CAM_PIN_D5 12
#define CAM_PIN_D6 11
#define CAM_PIN_D7 48

#elif CONFIG_MILLI_CAMERA_PINOUT_CUSTOM
#define CAMERA_PINS_NAME "custom (menuconfig)"
#define CAM_PIN_PWDN CONFIG_MILLI_CAM_PIN_PWDN
#define CAM_PIN_RESET CONFIG_MILLI_CAM_PIN_RESET
#define CAM_PIN_VSYNC CONFIG_MILLI_CAM_PIN_VSYNC
#define CAM_PIN_HREF CONFIG_MILLI_CAM_PIN_HREF
#define CAM_PIN_PCLK CONFIG_MILLI_CAM_PIN_PCLK
#define CAM_PIN_XCLK CONFIG_MILLI_CAM_PIN_XCLK
#define CAM_PIN_SIOD CONFIG_MILLI_CAM_PIN_SIOD
#define CAM_PIN_SIOC CONFIG_MILLI_CAM_PIN_SIOC
#define CAM_PIN_D0 CONFIG_MILLI_CAM_PIN_D0
#define CAM_PIN_D1 CONFIG_MILLI_CAM_PIN_D1
#define CAM_PIN_D2 CONFIG_MILLI_CAM_PIN_D2
#define CAM_PIN_D3 CONFIG_MILLI_CAM_PIN_D3
#define CAM_PIN_D4 CONFIG_MILLI_CAM_PIN_D4
#define CAM_PIN_D5 CONFIG_MILLI_CAM_PIN_D5
#define CAM_PIN_D6 CONFIG_MILLI_CAM_PIN_D6
#define CAM_PIN_D7 CONFIG_MILLI_CAM_PIN_D7

#else
#undef CAMERA_PINS_CONFIGURED
#define CAMERA_PINS_CONFIGURED 0
#define CAMERA_PINS_NAME "not configured"
#endif
