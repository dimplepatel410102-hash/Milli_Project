"""Camera capture route."""

from typing import Annotated

from fastapi import APIRouter, Header, Request, Security

from app.api.deps import authorize_device, device_api_key, require_device_id
from app.api.uploads import extract_image
from app.core.errors import DeviceNotRegistered, MilliError
from app.core.logging import get_logger
from app.schemas.camera import CaptureResponse
from app.schemas.errors import ErrorResponse
from app.services.capture import process_capture

logger = get_logger()

router = APIRouter(prefix="/camera", tags=["camera"])

_ERRORS = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    501: {"model": ErrorResponse},
}


@router.post(
    "/capture",
    response_model=CaptureResponse,
    responses=_ERRORS,
    summary="Accept a captured image",
    description=(
        "Accepts original image bytes from a registered device. "
        "The image format is detected from the bytes. "
        "Phase 1 does not run face detection, so face_detected is null and "
        "face_detection_performed is false. "
        "device_reported_face records an unverified device claim and is not a detection result."
    ),
)
async def capture_image(
    request: Request,
    api_key: Annotated[str | None, Security(device_api_key)] = None,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> CaptureResponse:
    device_id: str | None = None
    try:
        device_id = require_device_id(x_device_id)
        authorize_device(device_id, api_key, request.app.state.credentials)
        if not request.app.state.registry.is_registered(device_id):
            raise DeviceNotRegistered(
                "Register the device before sending captures.",
                received=False,
                face_detection_performed=False,
            )
        image_bytes, device_reported_face = await extract_image(
            request,
            request.app.state.settings.max_image_bytes,
        )
        result = process_capture(
            settings=request.app.state.settings,
            detector=request.app.state.detector,
            device_id=device_id,
            image_bytes=image_bytes,
            device_reported_face=device_reported_face,
        )
    except MilliError as exc:
        exc.received = False
        exc.face_detection_performed = False
        logger.warning(
            "Capture rejected device_id=%s status=rejected error=%s",
            device_id or "-",
            exc.code,
        )
        raise

    return CaptureResponse(
        capture_id=result.capture_id,
        device_id=result.device_id,
        received=result.received,
        received_at=result.received_at,
        image_bytes=result.image_bytes,
        image_format=result.image_format,
        face_detection_performed=result.face_detection_performed,
        face_detected=result.face_detected,
        detection_source=result.detection_source,
        device_reported_face=result.device_reported_face,
        message=result.message,
    )
