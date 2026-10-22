# Milli Backend — Phase 1

FastAPI backend for the Milli receptionist. Phase 1 receives images captured by an
ESP32-S3 device over Wi-Fi/HTTP, authenticates the device, validates the image, and
optionally runs server-side face detection.

This phase is **backend only**. There is no frontend, no webcam access, no firmware,
and no face recognition.

## What works and what is a placeholder

| Feature | Status | Notes |
|---|---|---|
| `GET /health` | Working | Status, version, environment, server time |
| Device registration | Working | Per-device API keys; registrations are **in memory** and lost on restart |
| Image upload | Working | Multipart or raw bytes. Format is detected from the bytes |
| Image validation | Working | Allowed formats, byte limit, pixel limit, corrupt/truncated detection |
| Error handling | Working | Consistent JSON errors (see table below) |
| Logging | Working | Device ID, capture ID, times, status, error code. No keys, no image data |
| Server-side face detection | Optional, off by default | `MILLI_FACE_DETECTOR=opencv_yunet` (OpenCV YuNet DNN, recommended) or `opencv_haar` (basic Haar cascade). Fine for bench tests, not for access decisions |
| Face enrollment and recognition | Optional, off by default | `MILLI_FACE_RECOGNITION=true`: OpenCV YuNet + SFace. Enrolled people get labels `Face 1`, `Face 2`, ...; others are `Unknown`. See [Face recognition](#face-recognition) |
| Device-reported detection | Pass-through | Headers from the device are echoed back as `device_detection`, marked `verified_by_server: false` |
| Temporary image storage | Optional, off by default | `MILLI_STORE_IMAGES=true`; old files are deleted after `MILLI_STORAGE_MAX_AGE_SECONDS` |
| Consent, liveness, attendance, visitors, appointments, business info/admin | **Placeholder** | Interfaces only, in `app/services/future.py`. Nothing returns data |

`GET /api/v1/features` returns this same status list as JSON.

**Face detection honesty:** with the default `MILLI_FACE_DETECTOR=none`, every response has
`face_detection_performed: false` and `server_detection.face_detected: null`. The server
never claims a face unless a detector actually ran on that image.

## Requirements

- Windows 10/11 with PowerShell (tested in Windows PowerShell 5.1)
- Python 3.11 or newer (tested with Python 3.14)
- `curl.exe` (included with Windows 10 and later) for the example commands

## Setup (PowerShell)

Run these from the project folder:

```powershell
cd C:\ESP32S3\Milli_Iot_Receptionist\milli_backend

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Optional: only if you want server-side face detection
.\.venv\Scripts\python.exe -m pip install -r requirements-detection.txt

Copy-Item .env.example .env
```

Every command here calls `.\.venv\Scripts\python.exe` directly, so you do not need to
activate the virtual environment or change the PowerShell execution policy.

### Create a device key

```powershell
.\.venv\Scripts\python.exe -m app.tools.device_key new dev-cam-01 --env-file .env
```

This prints the API key **once** and writes only its SHA-256 digest to
`MILLI_DEVICE_CREDENTIALS` in `.env`. Save the printed key; the device sends it in the
`X-Device-Key` header. Run the command again with another ID to add more devices.
If you lose a key, generate a new one for that device; the old one stops working.

## Run the server

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Health: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs> (click **Authorize** and enter `X-Device-ID` and `X-Device-Key`)
- ReDoc: <http://127.0.0.1:8000/redoc>

The server reads `.env` from the current folder, so start it from the project folder.

To accept uploads from an ESP32 on your LAN later, use `--host 0.0.0.0` and allow TCP
port 8000 through Windows Defender Firewall for private networks only.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The tests cover the health endpoint, Swagger/OpenAPI, device authentication, image
upload validation, size limits, error handling, storage, the device-key tool, and log
redaction. If OpenCV is installed, one more test runs the Haar detector end to end.

## Test without camera hardware

Generate synthetic test images. They are plain gradients with no faces in them:

```powershell
.\.venv\Scripts\python.exe scripts\make_sample_images.py
```

This creates `samples\sample.jpg`, `.png`, `.bmp`, `.gif`, `truncated.jpg` and `not_an_image.txt`.

### One-shot smoke test

With the server running, in a second PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 -DeviceKey "<your API key>"
```

It runs 13 checks (success and error cases) and prints PASS/FAIL for each.

### Individual commands

Set these once per PowerShell window:

```powershell
$base = "http://127.0.0.1:8000"
$id   = "dev-cam-01"
$key  = "<your API key>"
$headers = @{ "X-Device-ID" = $id; "X-Device-Key" = $key }
```

Health:

```powershell
Invoke-RestMethod "$base/health"
```

Register the device:

```powershell
$body = @{ firmware_version = "0.1.0"; hardware_model = "ESP32-S3-N16R8"; on_device_face_detection = $false } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/api/v1/devices/register" -Headers $headers -ContentType "application/json" -Body $body
```

Upload an image as raw bytes. This is the simplest option for ESP-IDF's `esp_http_client`:

```powershell
Invoke-RestMethod -Method Post "$base/api/v1/camera/capture" -Headers $headers -ContentType "application/octet-stream" -InFile samples\sample.jpg | ConvertTo-Json -Depth 5
```

Upload as multipart form data (field name `image`):

```powershell
curl.exe -s -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: $key" -F "image=@samples/sample.png"
```

Upload with optional device metadata headers:

```powershell
curl.exe -s -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: $key" `
  -H "Content-Type: application/octet-stream" `
  -H "X-Capture-Id: seq-000001" -H "X-Captured-At: 2026-10-21T07:15:00Z" `
  -H "X-Device-Face-Detected: true" -H "X-Device-Face-Count: 1" -H "X-Device-Detector: esp-dl" `
  --data-binary "@samples/sample.jpg"
```

Error cases (use `-w " [%{http_code}]"` to see the status code):

```powershell
curl.exe -s -w " [%{http_code}]" -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: wrong" --data-binary "@samples/sample.jpg"    # 401
curl.exe -s -w " [%{http_code}]" -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: $key" --data-binary "@samples/not_an_image.txt"  # 415
curl.exe -s -w " [%{http_code}]" -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: $key" --data-binary "@samples/truncated.jpg"     # 422
curl.exe -s -w " [%{http_code}]" -X POST "$base/api/v1/camera/capture" -H "X-Device-ID: $id" -H "X-Device-Key: $key" -H "Content-Type: application/octet-stream"  # 400
```

In Windows PowerShell, `curl` (without `.exe`) is an alias for `Invoke-WebRequest`, so
always type `curl.exe`.

## API

All device endpoints require two headers:

| Header | Value |
|---|---|
| `X-Device-ID` | Device ID listed in `MILLI_DEVICE_CREDENTIALS` (letters, digits, `-`, `_`; max 64) |
| `X-Device-Key` | The device's API key |

### `POST /api/v1/devices/register`

JSON body: `firmware_version` (required), `hardware_model`, `camera_model`, `on_device_face_detection`.
The response includes upload guidance for the firmware: endpoint, byte limit, allowed formats.

### `POST /api/v1/camera/capture`

The image can be sent in either of two ways:

- `multipart/form-data` with a single file field named `image`
- raw bytes as the request body, with any non-multipart `Content-Type` (`application/octet-stream`, `image/jpeg`, or the
  `application/x-www-form-urlencoded` default of `esp_http_client`/curl)

The format is detected from the bytes. `Content-Type` and file names are never trusted.
Default allowed formats are JPEG, PNG, BMP and WEBP (`MILLI_ALLOWED_IMAGE_FORMATS`). Raw
sensor frames such as RGB565 or YUV have no header to identify them, so they are not
accepted in Phase 1. The firmware should send an encoded format, normally the camera's
JPEG output.

Optional headers, all validated:

| Header | Meaning |
|---|---|
| `X-Capture-Id` | Device-side ID or sequence number |
| `X-Captured-At` | Capture time, ISO 8601 or Unix seconds |
| `X-Device-Face-Detected` | `true`/`false` from on-device detection |
| `X-Device-Face-Count` | 0–100; requires `X-Device-Face-Detected` |
| `X-Device-Detector` | Name of the on-device detector, e.g. `esp-dl` |

Example response, using the default settings:

```json
{
  "capture_id": "3c22644fccb04db5890511b27d7c6fdf",
  "device_id": "dev-cam-01",
  "status": "received",
  "image_received": true,
  "face_detection_performed": false,
  "received_at": "2026-10-21T07:10:21.022321Z",
  "captured_at": null,
  "device_capture_id": null,
  "image": { "format": "JPEG", "width": 320, "height": 240, "mode": "RGB", "size_bytes": 4692 },
  "server_detection": {
    "performed": false, "detector": null, "face_detected": null, "face_count": null, "faces": [],
    "message": "Server-side face detection is disabled (MILLI_FACE_DETECTOR=none); no detection was run."
  },
  "device_detection": { "reported": false, "face_detected": null, "face_count": null, "detector": null, "verified_by_server": false },
  "stored": false
}
```

Every capture response also has a `recognition` object (see [Face recognition](#face-recognition)).

### Face recognition

Setup, once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-detection.txt
.\.venv\Scripts\python.exe scripts\download_models.py
```

Start the server with recognition on (and image storage, so camera captures can be enrolled):

```powershell
$env:MILLI_FACE_RECOGNITION="true"; $env:MILLI_STORE_IMAGES="true"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Endpoints (device auth headers required; production needs a separate admin credential):

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/faces/enroll?employee_id=E001` | Body: a photo with exactly one face (raw or multipart `image`). Optional `label`; default is `Face 1`, `Face 2`, ... in enrollment order. Enrolling the same ID again adds a sample |
| `POST /api/v1/faces/enroll?employee_id=E001&capture_id=<id>` | Enroll from a capture the server stored (`MILLI_STORE_IMAGES=true`); best accuracy, because it is the same camera |
| `GET /api/v1/faces` | List enrolled people (no embeddings) |
| `DELETE /api/v1/faces/E001` | Delete a person's face data |

`recognition` in each capture response:

```json
"recognition": {
  "performed": true, "status": "recognized", "label": "Face 1", "employee_id": "E001",
  "similarity": 0.62, "distance": 0.38, "threshold": 0.363,
  "face": { "x": 101, "y": 52, "width": 88, "height": 110, "confidence": 0.93 },
  "message": "Matched Face 1 (similarity 0.620 >= 0.363)."
}
```

| `status` | `label` | Meaning |
|---|---|---|
| `recognized` | `Face N` | Similarity to an enrolled person ≥ `MILLI_FACE_MATCH_THRESHOLD` |
| `unknown` | `Unknown` | A face was found but matched nobody |
| `no_enrolled_faces` | `Unknown` | Nobody is enrolled yet |
| `no_face` | `null` | YuNet found no face, so recognition did not run |
| `disabled` | `null` | `MILLI_FACE_RECOGNITION=false` |

Only embeddings are stored (in `MILLI_FACE_DB_PATH`, default `data/faces.json`), not photos.
They are biometric data: get consent, keep the file private, and delete people on request.

### Errors

Every error has the same shape: `{"error": {"code": "...", "message": "...", "details": [...]}}`.

| HTTP | `code` | When |
|---|---|---|
| 400 | `missing_image` | Empty body, or multipart without an `image` field |
| 400 | `invalid_request` | Malformed request, inconsistent metadata headers, invalid `Content-Length` |
| 401 | `unauthorized_device` | Missing, unknown, or wrong device credentials (unknown IDs and wrong keys get the same message, to prevent ID probing) |
| 403 | `device_not_registered` | `MILLI_REQUIRE_REGISTRATION=true` and the device has not registered since the server started |
| 413 | `payload_too_large` | Body or image over the configured limit |
| 415 | `unsupported_image` | Not an image, or a format that is not allowed |
| 422 | `invalid_image` | Corrupt or truncated image, or too many pixels |
| 422 | `validation_error` | Invalid JSON body or header values |
| 422 | `no_face_detected` / `multiple_faces` | Enrollment photo without exactly one face |
| 404 | `not_found` | Unknown employee ID or stored capture |
| 500 | `processing_failed` | Detector, recognition or storage failure (internal details are logged, not returned) |
| 503 | `recognition_disabled` | `/faces` endpoints while `MILLI_FACE_RECOGNITION=false` |

## Configuration

All settings are environment variables, which can be set in `.env`. See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `MILLI_ENVIRONMENT` | `development` | `development`, `test`, `production` |
| `MILLI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MILLI_ENABLE_DOCS` | `true` | Serve `/docs`, `/redoc` and `/openapi.json` |
| `MILLI_DEVICE_CREDENTIALS` | empty | `id:sha256,id:sha256`; generate with `app.tools.device_key` |
| `MILLI_REQUIRE_REGISTRATION` | `false` | Require registration before uploads |
| `MILLI_MAX_IMAGE_BYTES` | `5242880` | Max image size (5 MiB); the request limit adds 64 KiB for multipart overhead |
| `MILLI_MAX_IMAGE_PIXELS` | `25000000` | Max width × height |
| `MILLI_ALLOWED_IMAGE_FORMATS` | `JPEG,PNG,BMP,WEBP` | Any of JPEG, PNG, BMP, WEBP, GIF, TIFF |
| `MILLI_FACE_DETECTOR` | `none` | `none`, `opencv_haar` or `opencv_yunet` |
| `MILLI_FACE_MIN_CONFIDENCE` | `0.6` | Minimum YuNet face confidence |
| `MILLI_FACE_RECOGNITION` | `false` | Enable YuNet + SFace recognition and the `/faces` endpoints |
| `MILLI_FACE_MATCH_THRESHOLD` | `0.363` | Minimum cosine similarity for a match |
| `MILLI_FACE_MODEL_DIR` | `models` | Folder with the ONNX models |
| `MILLI_FACE_DB_PATH` | `data/faces.json` | Enrolled embeddings |
| `MILLI_STORE_IMAGES` | `false` | Write received images to disk |
| `MILLI_STORAGE_DIR` | `data/captures` | Storage folder (one subfolder per device) |
| `MILLI_STORAGE_MAX_AGE_SECONDS` | `3600` | Delete stored images older than this; `0` keeps them |

## Security notes

- **Production requires HTTPS.** Device keys travel in headers and are readable on plain
  HTTP. Put the backend behind a TLS-terminating reverse proxy (e.g. Caddy, nginx, IIS),
  and have the ESP32 firmware verify the server certificate (`esp_http_client` with a CA
  certificate bundle).
- **Credentials:** only SHA-256 digests of device keys are stored on the server. `.env` is
  for development only and is git-ignored. In production, inject `MILLI_DEVICE_CREDENTIALS`
  from a secret manager (e.g. Azure Key Vault, AWS Secrets Manager, Docker/Kubernetes
  secrets). On the device, keep the key in encrypted NVS, not in source code.
- Keys are compared in constant time. Unknown devices and wrong keys get the same error.
- Request bodies are size-limited before they are read (`Content-Length`) and while they
  stream (chunked uploads). Images are decoded only by the allowed Pillow decoders, with
  pixel limits that guard against decompression bombs.
- Logs never contain API keys or image bytes. Images are not written to disk unless
  `MILLI_STORE_IMAGES=true`.
- Set `MILLI_ENABLE_DOCS=false` in production. Rate limiting is not built in yet; add it at
  the reverse proxy.
- Face images are biometric data. Before Phase 2 stores or matches faces, consent handling
  and a retention policy must be in place, as required by the applicable privacy law
  (e.g. GDPR, India's DPDP Act).

## Project layout

```
milli_backend/
  app/
    main.py                 ASGI entry point (uvicorn app.main:app)
    factory.py              create_app(): wires settings, services, routes
    api/
      deps.py               device authentication dependencies
      router.py             /api/v1 router
      routes/               health, devices, camera, faces, features
    core/
      config.py             settings (MILLI_* env vars / .env)
      security.py           API key hashing and verification
      errors.py             error types and JSON error handlers
      limits.py             request body size middleware
      logging.py
    schemas/                Pydantic request/response models
    services/
      images.py             image validation (format sniffing, limits)
      detection.py          FaceDetector interface + none / opencv_haar
      recognition.py        YuNet detector, SFace embeddings, enrolled-face database
      capture.py            capture pipeline
      storage.py            optional temporary storage
      registry.py           in-memory device registry
      future.py             interfaces for planned features (not implemented)
    tools/device_key.py     device API key generator
  scripts/
    make_sample_images.py   synthetic test images (no faces, no webcam)
    download_models.py      YuNet + SFace ONNX models (verified with OpenCV)
    download_test_faces.py  public-domain portraits for the real-model test
    smoke_test.ps1          end-to-end checks against a running server
  tests/
  requirements.txt          runtime dependencies
  requirements-dev.txt      + pytest, httpx2
  requirements-detection.txt  + OpenCV (optional)
  .env.example
```

## Notes for Phase 2 (ESP32-S3 firmware)

Not started; it waits for your confirmation that this backend works. The backend already
expects this flow from the firmware:

1. On boot, after Wi-Fi connects: `POST /api/v1/devices/register` with the auth headers.
2. When a face is detected on the device: `POST /api/v1/camera/capture` with the camera's
   JPEG frame as the raw body. Add `X-Device-Face-Detected` and the other metadata headers
   if the firmware runs its own detection.
3. If the response is 401, stop and report a configuration error. If it is 403, register
   again and retry. If it is 413, 415 or 422, fix the capture settings. If it is 5xx or the
   network fails, retry with backoff.

To add a better server-side detector later (e.g. a DNN model), implement the
`FaceDetector` protocol in `app/services/detection.py` and add it to `build_face_detector`.
