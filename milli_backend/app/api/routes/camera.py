import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.deps import AuthenticatedDevice, capture_device, get_capture_service
from app.core.errors import InvalidRequest, MilliError, MissingImage
from app.schemas.camera import CaptureResponse, DeviceCaptureMetadata
from app.schemas.common import error_responses
from app.services.capture import CaptureService

logger = logging.getLogger("milli.camera")

router = APIRouter(prefix="/camera", tags=["camera"])

MULTIPART_FIELD = "image"

_binary = {"schema": {"type": "string", "format": "binary"}}
IMAGE_REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "description": (
            "The image bytes exactly as captured. Send either a multipart form with an `image` file field, "
            "or the raw bytes as the request body. The format is detected from the bytes; "
            "Content-Type and file names are not trusted."
        ),
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": [MULTIPART_FIELD],
                    "properties": {MULTIPART_FIELD: {"type": "string", "format": "binary"}},
                }
            },
            "application/octet-stream": _binary,
            "image/*": _binary,
        },
    }
}


def capture_metadata(
    device_capture_id: str | None = Header(
        None, alias="X-Capture-Id", max_length=64, pattern=r"^[A-Za-z0-9._-]+$",
        description="Optional ID/sequence number assigned by the device.",
    ),
    captured_at: datetime | None = Header(
        None, alias="X-Captured-At", description="Optional capture time (ISO 8601 or Unix seconds)."
    ),
    face_detected: bool | None = Header(
        None, alias="X-Device-Face-Detected",
        description="Optional result of on-device face detection. Passed through, not verified.",
    ),
    face_count: int | None = Header(None, alias="X-Device-Face-Count", ge=0, le=100),
    detector: str | None = Header(
        None, alias="X-Device-Detector", max_length=32, pattern=r"^[A-Za-z0-9._-]+$",
        description="Optional name of the on-device detector, e.g. esp-dl.",
    ),
) -> DeviceCaptureMetadata:
    return DeviceCaptureMetadata(
        device_capture_id=device_capture_id,
        captured_at=captured_at,
        face_detected=face_detected,
        face_count=face_count,
        detector=detector,
    )


async def read_image_bytes(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form(max_files=1, max_fields=10)
        try:
            upload = form.get(MULTIPART_FIELD)
            if upload is None:
                raise MissingImage(f"Multipart field '{MULTIPART_FIELD}' is missing.")
            if not isinstance(upload, UploadFile):
                raise InvalidRequest(f"Multipart field '{MULTIPART_FIELD}' must be a file upload.")
            data = await upload.read()
        finally:
            await form.close()
    else:
        # Any other Content-Type is read as raw bytes: esp_http_client and curl --data-binary
        # default to application/x-www-form-urlencoded, and the bytes are validated anyway.
        data = await request.body()

    if not data:
        raise MissingImage()
    return data


@router.post(
    "/capture",
    response_model=CaptureResponse,
    summary="Upload an image captured by a device",
    description=(
        "Authenticates the device, validates the uploaded image and, if configured, runs server-side "
        "face detection and recognition. `face_detection_performed` and `recognition.performed` are "
        "false unless that step actually ran."
    ),
    openapi_extra=IMAGE_REQUEST_BODY,
    responses=error_responses(400, 401, 403, 413, 415, 422, 500),
)
async def capture(
    request: Request,
    device: AuthenticatedDevice = Depends(capture_device),
    metadata: DeviceCaptureMetadata = Depends(capture_metadata),
    service: CaptureService = Depends(get_capture_service),
) -> CaptureResponse:
    try:
        data = await read_image_bytes(request)
        return await run_in_threadpool(
            service.process, device_id=device.device_id, data=data, metadata=metadata
        )
    except MilliError as exc:
        logger.warning(
            "capture rejected device_id=%s status=%d code=%s",
            device.device_id, exc.status_code, exc.code,
        )
        raise
