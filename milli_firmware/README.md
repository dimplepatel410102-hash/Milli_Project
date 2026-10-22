# Milli Phase 2 firmware: ESP32-S3 N16R8 + GC2145

ESP-IDF firmware that captures frames from a GC2145 camera, runs on-device face
detection (ESP-DL), and uploads a frame to the Phase 1 backend
(`../milli_backend`) when a face is present. Employee recognition and
attendance are out of scope for this phase.

> **Hardware status:** the firmware builds and its upload path is verified in
> the ESP-IDF QEMU emulator against the real backend, but **no hardware test
> has been run yet**. The board was not connected, and the camera pin mapping
> is unknown. The camera stays disabled until you enter pins from your board's
> documentation and mark them verified. See [Test report](#test-report).

## How it works

```
GC2145 --RGB565 QVGA--> camera_manager --> face_detection (ESP-DL MSR+MNP)
                                                   |
                                         capture_policy (presence, cooldown,
                                                   |      duplicate suppression)
                                     face present  v
                              encode JPEG/BMP (esp32-camera converters)
                                                   |
                           upload task --HTTP POST raw body--> /api/v1/camera/capture
                                                   |
                       success only on 200 + {"status":"received","image_received":true}
```

| File | Purpose |
|---|---|
| `main/main.c` | Boot banner, init order, tasks (camera/detection on core 1, upload on core 0), status log every 60 s |
| `main/network_manager.c/.h` | Wi-Fi station, reconnect with exponential backoff (1 s up to `MILLI_WIFI_MAX_BACKOFF_MS`) |
| `main/camera_manager.c/.h` | esp32-camera init from menuconfig pins, pin sanity checks, GC2145 PID check (0x2145), frame validation |
| `main/face_detection.cpp/.h` | ESP-DL `HumanFaceDetect` wrapper with a C API. It is C++ because ESP-DL's API is C++ only |
| `main/capture_policy.c/.h` | Decides when a face frame is uploaded (see [Capture policy](#capture-policy)) |
| `main/image_uploader.c/.h` | Registration and capture upload, response validation, bounded retries |
| `main/Kconfig.projbuild` | All settings (`idf.py menuconfig` → *Milli configuration*) |
| `sdkconfig.defaults` | N16R8 flash/PSRAM, CPU, face model, GC2145 driver |
| `partitions.csv` | 6 MB factory app partition (16 MB flash) |
| `test_apps/upload_qemu/` | Emulator test of policy, encoders and uploader against the real backend |

### Image format

GC2145 has no hardware JPEG, and the backend only accepts encoded images
(JPEG/PNG/BMP/WEBP), so frames are encoded on the device. The format is
configurable (*Upload image format*):

- **JPEG (default)**, quality 80. A QVGA frame is typically a few KB to tens of KB.
- **BMP**: uncompressed, 230 KB for QVGA. Use it only if you need lossless frames.

Detection runs on the raw RGB565 frame. Encoding happens only for frames that
will be uploaded.

### Backend contract used

- `POST {MILLI_SERVER_URL}/api/v1/devices/register` with JSON
  `firmware_version`, `hardware_model`, `camera_model` (only if the sensor was
  detected), and `on_device_face_detection`.
- `POST {MILLI_SERVER_URL}{MILLI_CAPTURE_ENDPOINT}` with the raw image body and
  these headers:
  - `Content-Type: image/jpeg` or `image/bmp`.
  - `X-Device-ID` and `X-Device-Key`.
  - `X-Capture-Id`: `b<boot id>-<sequence>`.
  - `X-Captured-At`: only after SNTP has synced.
  - `X-Device-Face-Detected`, `X-Device-Face-Count`, and `X-Device-Detector: esp-dl-msrmnp-s8-v1`.
- **Success** means HTTP 200 **and** `status == "received"` **and**
  `image_received == true`. Anything else is logged as `NOT received`.
- **Retried** with backoff (first delay `MILLI_UPLOAD_BACKOFF_MS`, doubled,
  capped at 10 s, at most `MILLI_UPLOAD_MAX_ATTEMPTS` attempts): no response,
  HTTP 5xx, 408, 429.
- **Not retried**: 400, 401 (bad credentials), 413, 415, 422.
- On **403 `device_not_registered`**, the firmware registers and retries once.

## Prerequisites

- ESP-IDF **v6.1** (installed at `C:\esp\v6.1\esp-idf`, tools at `C:\Espressif\tools`).
- Internet access for the first build. The component manager downloads the
  versions pinned in `dependencies.lock`:
  - `espressif/esp32-camera` 2.1.8
  - `espressif/human_face_detect` 0.5.1
  - `espressif/esp-dl` 3.3.14
  - `espressif/cjson` 1.7.19
- The Phase 1 backend running on your PC and reachable from the ESP32's Wi-Fi network.

## Configuration

Everything is set in `idf.py menuconfig` → **Milli configuration**. Values are
stored in `sdkconfig`, which is git-ignored because it will contain your Wi-Fi
password and device key. Nothing secret is in the source files, and the
firmware never logs the Wi-Fi password or API key (the boot log shows the key
only as `set` / `(not set)`).

| Menu | Setting | Notes |
|---|---|---|
| Wi-Fi | SSID, password | 2.4 GHz only |
| Milli backend | `MILLI_SERVER_URL` | e.g. `http://192.168.1.50:8000` (your PC's LAN IP, not `127.0.0.1`) |
| | `MILLI_DEVICE_ID` | must exist in the backend's `MILLI_DEVICE_CREDENTIALS` |
| | `MILLI_DEVICE_API_KEY` | from `python -m app.tools.device_key new <id>` |
| | `MILLI_CAPTURE_ENDPOINT` | default `/api/v1/camera/capture` |
| | timeout, attempts, backoff | defaults 10 s, 3 attempts, 1 s |
| Camera pins | every GPIO + "I have verified these pins" | see [Wiring](#wiring) |
| Camera capture | QVGA (default) / VGA, mirror, flip | |
| Upload image format | JPEG (default) / BMP, JPEG quality | |
| Face detection and capture policy | mode, min score, confirm/absent frames, cooldown, min interval | |
| Time | SNTP on/off, server | without SNTP, `X-Captured-At` is omitted and the server uses its receive time |

**Run mode** `Camera test only` captures frames and logs size, fps and a
brightness value every 2 s. It does no detection and no upload. Use it to bring
up the camera before enabling face detection.

### Backend setup for the device (development, plain HTTP on the LAN)

In `milli_backend`:

```powershell
# 1. Create a device key (prints the key once; stores only its hash in .env)
.\.venv\Scripts\python.exe -m app.tools.device_key new lobby-cam-01 --env-file .env

# 2. Listen on the LAN instead of localhost only
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. Allow inbound port 8000 on private networks (run PowerShell as Administrator, once)
New-NetFirewallRule -DisplayName "Milli backend 8000 (dev)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private

# 4. Find the PC's LAN IP for MILLI_SERVER_URL
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' } | Select-Object InterfaceAlias, IPAddress
```

> **Production:** plain HTTP sends the device key in clear text and is for
> development on a trusted LAN only. In production, use an `https://` URL. The
> firmware then validates the server with the ESP-IDF certificate bundle.
> Production also needs secure credential management: unique keys per device,
> rotation, flash encryption and secure boot so keys cannot be read from flash.

## Build, flash, monitor (Windows PowerShell)

```powershell
# Load ESP-IDF into this PowerShell session (needed in every new terminal)
. C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1

cd C:\ESP32S3\Milli_Iot_Receptionist\milli_firmware

idf.py set-target esp32s3      # only once; already done in this repo
idf.py menuconfig              # Milli configuration -> Wi-Fi, backend, camera pins
idf.py build

# Find the board's COM port (plug the board in first)
[System.IO.Ports.SerialPort]::GetPortNames()
Get-PnpDevice -Class Ports -PresentOnly | Select-Object FriendlyName, Status

idf.py -p COM5 flash monitor   # replace COM5; exit the monitor with Ctrl+]
idf.py -p COM5 monitor         # monitor only
```

Logs appear on the UART port and on the native USB port (USB-Serial-JTAG), so
either USB connector on a two-port N16R8 dev board works.

`idf.py flash` only overwrites the bootloader, partition table and app. **Do not
run `idf.py -p COMx erase-flash` unless you specifically want to wipe the old
firmware and NVS.** It is not needed for normal use.

## Wiring

**The camera pins are intentionally blank.** GC2145 boards and ESP32-S3 dev
boards come with many different connectors and pin mappings. The firmware must
not guess them: wrong pins can short outputs or drive the camera at the wrong
voltage. Fill this table from **your** board's schematic or vendor pin table,
enter the values in menuconfig, then enable *I have verified these pins*.

| Camera signal | Function | ESP32-S3 GPIO (from your board docs) |
|---|---|---|
| SIOD | SCCB/I2C data | ____ |
| SIOC | SCCB/I2C clock | ____ |
| XCLK | camera master clock (or -1 if the module has an oscillator) | ____ |
| PCLK | pixel clock | ____ |
| VSYNC | frame sync | ____ |
| HREF | line valid | ____ |
| D0 (Y2) … D7 (Y9) | 8-bit data | ____ ×8 |
| PWDN | power-down (-1 if not connected) | ____ |
| RESET | reset (-1 if not connected) | ____ |
| 3V3 / GND | power | check the camera board's required supply voltage |

The firmware rejects these pin choices at boot:

- **GPIO26–37:** on N16R8 modules these are wired to the 16 MB flash and the
  8 MB octal PSRAM. This is an error.
- **GPIO19/20:** these are the USB D-/D+ pins, so native USB stops working.
  This is a warning.
- **Duplicate GPIOs:** an error.

### Mapping in use (user-confirmed)

The board in use is a dual USB-C "ESP32-S3 WROOM" CAM board with an
ESP32-S3-N16R8 module and an on-board 24-pin camera connector. On
2026-10-21 the user confirmed that the seller's pinout matches the mapping
published for the Freenove ESP32-S3-WROOM CAM board. That mapping is set in
the local `sdkconfig`:

| Signal | GPIO | Signal | GPIO | Signal | GPIO |
|---|---|---|---|---|---|
| SIOD | 4 | D7 (Y9) | 16 | D3 (Y5) | 10 |
| SIOC | 5 | D6 (Y8) | 17 | D2 (Y4) | 8 |
| XCLK | 15 | D5 (Y7) | 18 | D1 (Y3) | 9 |
| PCLK | 13 | D4 (Y6) | 12 | D0 (Y2) | 11 |
| VSYNC | 6 | HREF | 7 | PWDN / RESET | -1 / -1 |

If you use a different board, re-check every value against that board's documentation.

## Capture policy

These settings prevent a person standing in front of the camera from being
uploaded over and over. All of them are configurable:

- **`MILLI_FACE_CONFIRM_FRAMES` (2):** a face must be seen in this many
  consecutive frames before the person counts as present. This filters single
  false detections.
- **`MILLI_FACE_ABSENT_FRAMES` (5):** this many consecutive empty frames end the
  presence. A brief detection dropout does not count as a new person.
- **One upload per presence:** the first upload happens on a frame that
  actually contains a face.
- **`MILLI_CAPTURE_COOLDOWN_MS` (30 s):** if the same person stays in view, the
  frame is re-uploaded at most once per cooldown. `0` means never.
- **`MILLI_MIN_UPLOAD_INTERVAL_MS` (5 s):** a hard floor between any two
  uploads, including retries after a failure and a new person arriving right
  after the last upload.
- **Failed upload:** the same presence stays eligible, subject to the minimum
  interval.
- **One upload in flight:** frames are not queued while an upload is running.
  If Wi-Fi is down when a face is detected, the upload is skipped, counted and
  logged, and the frame is not buffered.
- **`MILLI_PERIODIC_UPLOAD_MS` (0 = off):** bench-test option that also uploads
  one frame every N ms while no face is detected on the device. Use it to check
  image quality and let the backend's detector and recognizer judge the frames
  when on-device detection finds nothing.

## Logs

- **Boot:**
  - Firmware and ESP-IDF version, chip, flash and PSRAM size, free heap.
  - Config summary: device ID, server URL, whether the key is set.
  - Camera result: the sensor name and PID, or `BLOCKED` with the reason.
- **Detection:** face count, score, box and latency whenever the face count changes.
- **Wi-Fi:** the SSID and the board's MAC address (to find it in a hotspot's
  device list), and every disconnect with its reason code and meaning.
- **Each capture:**
  - `capture b1a2b3c4-7 (face detected): 1 face(s) on device, encoded 320x240 to 14532 bytes image/jpeg in 41 ms`
  - JPEG output is checked for start/end markers and buffer truncation before upload.
  - Then `server confirmed capture_id=… format=JPEG, server found 1 face(s)` and the server's
    recognition result: `RECOGNIZED: Face 1 (employee E001, similarity 0.62)`,
    `RECOGNITION: Unknown person (best similarity 0.12)`, or `recognition <status>: <message>`.
  - Then `capture … RECEIVED by server as <capture_id>` or `capture … NOT received: HTTP <code> <error>`.
- **Every 60 s, a status line:** Wi-Fi, registration, camera state, frame and
  face counters, `best_face_score` (the highest detector score in the last
  minute, including rejected candidates, next to the threshold it needs),
  uploads ok/failed/offline, and heap.

## Emulator test (no board needed)

`test_apps/upload_qemu` runs in the ESP-IDF QEMU emulator (ESP32-S3 with
emulated Ethernet). It compiles the firmware's real `image_uploader.c` and
`capture_policy.c` and checks:

- the capture policy rules;
- the esp32-camera JPEG and BMP encoders on a synthetic color-bar frame;
- uploads against the real backend on the PC, reached through QEMU's `10.0.2.2`.

The test image is reported to the server as **0 faces**, never as a detection.

```powershell
# Backend: create a throwaway test key (do not use a real device key)
cd C:\ESP32S3\Milli_Iot_Receptionist\milli_backend
.\.venv\Scripts\python.exe -m app.tools.device_key new qemu-test-01
#   -> put "Credential" into the env var below,
#      and the key into test_apps\upload_qemu\sdkconfig.local (git-ignored):
#        CONFIG_TEST_DEVICE_ID="qemu-test-01"
#        CONFIG_TEST_DEVICE_API_KEY="<key>"
$env:MILLI_DEVICE_CREDENTIALS = "qemu-test-01:<sha256 from the tool>"
$env:MILLI_REQUIRE_REGISTRATION = "true"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Second terminal: build and run the test firmware in QEMU
. C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1
cd C:\ESP32S3\Milli_Iot_Receptionist\milli_firmware\test_apps\upload_qemu
idf.py -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.local" build
idf.py qemu          # ends with "=== RESULT: N passed, M failed ==="; stop with Ctrl+A then X
```

The main firmware also boots in QEMU (`idf.py qemu --qemu-extra-args="-m 8M"`
in `milli_firmware`). Wi-Fi and the camera are not emulated, so this only
checks the boot sequence.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `idf.py` not recognized | Run `. C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1` in this terminal first |
| Flash: `Failed to connect to ESP32-S3` | Wrong COM port, a charge-only cable, or the board is not in download mode: hold **BOOT**, tap **RESET**, release BOOT, then retry |
| No COM port appears | Try the other USB connector. A CH340/CP210x port needs the vendor driver; the native USB port needs none |
| `PSRAM not detected` at boot | The board is not an octal-PSRAM (R8) module, or `CONFIG_SPIRAM_MODE_OCT` was changed. The camera needs PSRAM |
| `camera disabled: pins are not verified` | Expected until the pins are entered and *I have verified these pins* is enabled |
| `pin X=GPIOn is used by flash/octal PSRAM` | That pin mapping cannot work on N16R8 (GPIO26–37); recheck the board docs |
| `esp_camera_init failed` / `Camera probe failed with error 0x…` | SIOD/SIOC swapped or wrong, no camera power, no XCLK (or XCLK set while the module has an oscillator), PWDN/RESET polarity, ribbon cable reversed |
| `expected GC2145 (PID 0x2145) but found …` | A different sensor is fitted; the firmware refuses to run it as a GC2145 |
| Many `frame capture timed out` / `discarding malformed frame` | Data/PCLK/VSYNC/HREF pin errors or a loose cable; try a lower XCLK (e.g. 10 MHz) |
| Image is mirrored/upside down | Toggle *Mirror horizontally* / *Flip vertically* |
| Image colors look wrong | Check for swapped data lines D0–D7 |
| `Wi-Fi disconnected (reason 201)` | SSID not found: 5 GHz-only network, typo, or out of range. The firmware then scans once and logs every 2.4 GHz network it can see (`scan: 2.4 GHz networks the ESP32 can see`). Use one of those SSIDs, enable 2.4 GHz on the router, or use a Windows Mobile Hotspot set to 2.4 GHz (then `MILLI_SERVER_URL=http://192.168.137.1:8000`) |
| `reason 5` | The access point (often a phone hotspot) refused the board: its connected-device limit is reached or the board's MAC is blocked. Raise the limit, unblock the device, or disconnect another device. If the PC is not on the same network, also update `MILLI_SERVER_URL` |
| `reason 15` / `204` / `2` | Wrong password or the AP uses an unsupported security mode |
| `no response (ESP_ERR_HTTP_CONNECT)` | Backend not running, bound to 127.0.0.1 instead of 0.0.0.0, Windows firewall, wrong IP in `MILLI_SERVER_URL`, or AP client isolation |
| `HTTP 401 unauthorized_device` | Device ID/key do not match the backend's `MILLI_DEVICE_CREDENTIALS`, or the backend was not restarted after editing `.env` |
| `HTTP 403 device_not_registered` | Backend has `MILLI_REQUIRE_REGISTRATION=true`; the firmware registers automatically. If it persists, check the registration log line |
| `HTTP 413` | Image larger than the backend's `MILLI_MAX_IMAGE_BYTES`; use JPEG or QVGA |
| `JPEG filled the encoder's 128 KB buffer` | Lower JPEG quality or use QVGA |
| No faces detected (`face_frames=0`) | Look at `best_face_score` in the status line while someone faces the camera. Near 0%: the detector sees nothing face-like; enable `MILLI_PERIODIC_UPLOAD_MS` with `MILLI_STORE_IMAGES=true` on the backend and open the stored JPEGs (`milli_backend\data\captures`) to check the image (focus, exposure, colors, orientation). Just below the threshold: improve lighting, move closer, or lower *Minimum face score* |
| `X-Captured-At` missing | SNTP has not synced (no internet on that network); the server uses its own receive time |

## Test report

Date: 2026-10-21. ESP-IDF v6.1.0 on Windows. Board: ESP32-S3 (QFN56) rev v0.2 with embedded 8 MB PSRAM, on COM6 (USB-Serial/JTAG). Dual USB-C "ESP32-S3 WROOM" CAM board; camera pin mapping confirmed by the user.

| # | Milestone | Result | Evidence |
|---|---|---|---|
| 1 | Firmware builds | **PASS** | `idf.py build` succeeds with zero warnings in both the default configuration (face detection + JPEG, app 2.23 MB, 63% partition free; rebuilt after the diagnostics changes) and a variant (camera-test mode + BMP + mirror + SNTP off). All `sdkconfig.defaults` keys verified present in the generated `sdkconfig`. |
| 2 | Board boots | **PASS** (hardware) | Flashed over native USB on COM6. The board boots: ESP32-S3 rev v0.2, 16 MB flash in QIO mode, 8 MB octal PSRAM (memory test OK), 240 MHz, 264 KB internal heap. The firmware prints its banner and config summary, reports each missing setting, and keeps the camera disabled because the pins are not verified. |
| 3 | Wi-Fi connects | **BLOCKED** (network) | The router network "UpNext24" is 5 GHz only (reason 201). The phone hotspot is seen and authenticates, then refuses the association with reason 5 (device limit reached or MAC blocked), on every retry. Needs a 2.4 GHz network that accepts the board. |
| 4 | GC2145 captures frames | **PASS** (hardware) | With the user-confirmed pin mapping, the sensor passed the GC2145 ID check (PID 0x2145); the firmware refuses to start the camera otherwise. Camera-test mode delivered 320×240 RGB565 frames (153,600 bytes each) at 34.6 fps: 4,141 frames in the first ~2 minutes, 0 capture errors. The brightness value moved between 2 and 39 of 63 as the scene and lens cover changed, so the frames are live images. |
| 5 | Face detection | **NOT YET CONFIRMED** (hardware) | The ESP-DL model loads and runs on live frames on the board (~37 ms per frame, 22,000+ frames), but `face_frames=0` so far. It is unknown whether a face was in view; the new `best_face_score` status field and periodic uploads are there to find out. |
| 9 | Server-side recognition | **PASS (backend, real models)**, **BLOCKED (hardware)** | Backend with OpenCV YuNet + SFace: two public-domain portraits enrolled as `Face 1` / `Face 2`; altered copies recognized (similarity 0.894 and 0.836), a third person returned `Unknown` (0.103, threshold 0.363). Same result over HTTP with `scripts\recognition_test.ps1`. Not yet run on ESP32 camera frames. |
| 6 | Backend connectivity | **PASS (emulator)**, **BLOCKED (hardware)** | In QEMU: registration returned HTTP 200, and the backend log shows the device registered. On hardware: needs Wi-Fi. |
| 7 | Image received by backend | **PASS (emulator)**, **BLOCKED (hardware)** | In QEMU: JPEG (3,268 B) and BMP (230,454 B) uploads were confirmed by the server with HTTP 200 and returned capture IDs. The stored files decode as 320×240 with all 8 color bars correct, which confirms the RGB565 byte order through both encoders. These were synthetic test-pattern frames, not camera frames. |
| 8 | Repeated captures, disconnects, failed uploads | **PARTIAL PASS (emulator)**, **BLOCKED (hardware)** | 17 capture-policy checks pass (confirm/absent hysteresis, cooldown, min interval, retry after failure, in-flight lock, presence change during upload). Uploader checks: unreachable server makes 3 attempts with 0.5 s and 1 s backoff, then fails; 401, 403 and 415 are not retried and never reported as success. Wi-Fi drop/reconnect is untested (needs hardware). |

Emulator test summary: `=== RESULT: 37 passed, 0 failed ===`.

**To unblock milestones 3 and 5–9 on hardware:** put the board on a 2.4 GHz network that also
reaches the PC (see `reason 5` / `reason 201` under [Troubleshooting](#troubleshooting)), set
`MILLI_SERVER_URL` to the PC's address on that network, start the backend with recognition
enabled, and enroll people from real camera captures.
