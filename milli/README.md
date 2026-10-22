# Milli Face Detection Backend — Phase 1

Local HTTP API for the Milli receptionist. This phase receives an image from an authorized device, validates that the bytes are a supported image, and reports that face detection did not run.

The ESP32-S3 firmware is a later phase. This service does not open a webcam and it does not produce recognition, attendance, or visitor results.

## What works

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Returns process status, service name, version, environment, and the detection mode. |
| `GET /docs` | Swagger UI. |
| `GET /openapi.json` | OpenAPI schema. |
| `POST /api/v1/devices/register` | Registers a device whose id and API key already exist in the server configuration. |
| `POST /api/v1/camera/capture` | Authenticates a registered device, validates the image bytes, and returns a capture receipt. |

A successful capture looks like this:

- `received` is `true` after the bytes decode as JPEG, PNG, BMP, GIF, WEBP, or TIFF.
- `face_detection_performed` is `false`.
- `face_detected` is `null`.
- `device_reported_face` only echoes an optional claim from the device. That claim is not a detection result.

The filename and the HTTP content type are not trusted. Format is identified from the bytes.

Images stay in memory for the request. They are not written to disk unless `MILLI_STORE_IMAGES=true`. Retained files are a local debugging option (`MILLI_RETAIN_TEMP_IMAGES=true`) and are named with the capture id.

Device registration is stored in memory and is cleared when the process stops. Configure the allowed devices with `MILLI_DEVICE_CREDENTIALS`.

## Placeholders

These interfaces exist in `app/services/future.py` and `app/services/detection.py`. They are not connected to routes and they do not return successful results:

- Server-side face detection (`MILLI_FACE_DETECTION_MODE=server` returns HTTP 501)
- Trusting an ESP32 face-detection result (`MILLI_FACE_DETECTION_MODE=device` returns HTTP 501)
- Employee enrollment and face recognition
- Attendance with timestamps
- Consent management and liveness checks
- Visitor handling
- Appointment check-in
- Business information and an admin panel
- ESP32-S3 N16R8 firmware

Leave `MILLI_FACE_DETECTION_MODE=disabled` for Phase 1. That mode accepts a valid image and records that no detector ran.

## Security

- Device API keys are read from the environment. No real key is stored in source code.
- `.env.example` uses a placeholder key. The server rejects that placeholder and any key shorter than 16 characters.
- Send the key in the `X-Device-Key` header, not in the JSON body or the query string.
- Logs include the device id, capture time, image size, detected format, and status. They do not include the API key or the image bytes.
- Request bodies are limited to `MILLI_MAX_IMAGE_BYTES` plus 8 KiB. The image itself cannot exceed `MILLI_MAX_IMAGE_BYTES` (maximum configurable value is 8 MiB).
- Production deployment requires HTTPS in front of this process and a secret store for device keys. This development server speaks plain HTTP and binds to `127.0.0.1` by default.

## Windows PowerShell setup

Run these commands from the backend directory. The firmware project in the parent folder is not part of this setup.

```powershell
cd C:\ESP32S3\Milli_Iot_Receptionist\milli
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If activation is blocked, you can keep using `.\.venv\Scripts\python.exe` as shown above. To activate the environment in the current PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Generate a development API key and put it in `.env`. Do not commit `.env`.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Edit `.env`:

```text
MILLI_DEVICE_CREDENTIALS=dev-device-001:paste-the-generated-key-here
```

The device id may contain letters, digits, `.`, `_`, and `-`. To configure a second device, add a comma and another `device_id:api_key` pair. Keys cannot contain spaces or commas.

## Run the server

From `C:\ESP32S3\Milli_Iot_Receptionist\milli`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

- Health: http://127.0.0.1:8000/health
- Swagger: http://127.0.0.1:8000/docs

Stop the server with Ctrl+C.

## Run the tests

From the same directory:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Test the API without a camera

In a second PowerShell window:

```powershell
cd C:\ESP32S3\Milli_Iot_Receptionist\milli
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

Load the device id and key from `.env`:

```powershell
$pair = ((Get-Content .env | Where-Object { $_ -like "MILLI_DEVICE_CREDENTIALS=*" }) -replace "^MILLI_DEVICE_CREDENTIALS=", "").Trim()
$deviceId, $apiKey = $pair.Split(":", 2)
```

Register the device:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/devices/register `
  -Headers @{ "X-Device-Key" = $apiKey } `
  -ContentType "application/json" `
  -Body (@{ device_id = $deviceId } | ConvertTo-Json)
```

Create a tiny PNG and upload it. PowerShell's `curl` alias is not curl, so the upload uses `curl.exe`.

```powershell
$png = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
[IO.File]::WriteAllBytes("$pwd\sample.png", $png)
curl.exe -s -X POST "http://127.0.0.1:8000/api/v1/camera/capture" `
  -H "X-Device-Id: $deviceId" `
  -H "X-Device-Key: $apiKey" `
  -F "image=@sample.png;type=application/octet-stream"
```

Expected capture fields include `"received": true`, `"face_detection_performed": false`, and `"face_detected": null`.

The same PNG can be sent as a raw body:

```powershell
curl.exe -s -X POST "http://127.0.0.1:8000/api/v1/camera/capture" `
  -H "X-Device-Id: $deviceId" `
  -H "X-Device-Key: $apiKey" `
  -H "Content-Type: application/octet-stream" `
  --data-binary "@sample.png"
```

An optional device claim is recorded and is not treated as detection:

```powershell
curl.exe -s -X POST "http://127.0.0.1:8000/api/v1/camera/capture" `
  -H "X-Device-Id: $deviceId" `
  -H "X-Device-Key: $apiKey" `
  -F "image=@sample.png" `
  -F "device_reported_face=true"
```

Examples that should fail:

```powershell
# Wrong key
curl.exe -s -D - -o NUL -X POST "http://127.0.0.1:8000/api/v1/devices/register" `
  -H "X-Device-Key: not-the-real-key" `
  -H "Content-Type: application/json" `
  --data-binary "{\"device_id\":\"$deviceId\"}"

# Not an image
Set-Content -Path "$pwd\notes.txt" -Value "hello" -Encoding ascii
curl.exe -s -X POST "http://127.0.0.1:8000/api/v1/camera/capture" `
  -H "X-Device-Id: $deviceId" `
  -H "X-Device-Key: $apiKey" `
  -F "image=@notes.txt"
```

The wrong key returns HTTP 401. The text file returns HTTP 415. Delete `sample.png` and `notes.txt` when you are finished. Both are gitignored.

## Capture contract for later hardware

When the ESP32-S3 firmware is written, it will call this API over Wi-Fi. Phase 1 does not include that firmware.

1. `POST /api/v1/devices/register` with header `X-Device-Key` and JSON `{"device_id":"..."}`.
2. `POST /api/v1/camera/capture` with headers `X-Device-Id` and `X-Device-Key`.
3. Send the original image bytes either as multipart field `image` or as a raw body with `Content-Type: application/octet-stream` (or `image/*`).
4. Optional unverified claim: form field `device_reported_face=true|false`, or header `X-Device-Reported-Face` for a raw body.

Supported image bytes are JPEG, PNG, BMP, GIF, WEBP, and TIFF. The camera format does not need to be chosen before the firmware work starts, as long as it is one of those.

To reach the board from the network later, change `MILLI_HOST` only when you are ready to listen beyond localhost, and put HTTPS in front of the service before any production use.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MILLI_DEVICE_CREDENTIALS` | empty | `device_id:api_key` pairs, comma-separated |
| `MILLI_FACE_DETECTION_MODE` | `disabled` | `disabled` accepts images without detection. `server` and `device` return HTTP 501 |
| `MILLI_MAX_IMAGE_BYTES` | `1048576` | Maximum image size |
| `MILLI_STORE_IMAGES` | `false` | Write a temporary file during processing |
| `MILLI_RETAIN_TEMP_IMAGES` | `false` | Keep that file after a successful capture |
| `MILLI_TEMP_DIR` | system temp `/milli` | Directory used only when storage is enabled |
| `MILLI_HOST` / `MILLI_PORT` | `127.0.0.1` / `8000` | Used by `python -m app.main` |
| `MILLI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

## Project layout

```text
milli/
  app/
    main.py              FastAPI app, Swagger, startup logging
    api/                 Routes, auth dependencies, upload reading
    core/                Settings, credentials, limits, errors, logging
    schemas/             Request and response models
    services/            Registry, image validation, detection interface, capture pipeline
  tests/
  requirements.txt
  .env.example
```

Image validation lives in `app/services/images.py`. The detection interface lives in `app/services/detection.py`. Routes do not decide whether a face is present.
