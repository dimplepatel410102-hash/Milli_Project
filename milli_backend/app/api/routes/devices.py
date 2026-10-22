import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from app.api.deps import AuthenticatedDevice, authenticate_device, get_registry, get_settings
from app.core.config import Settings
from app.schemas.common import error_responses
from app.schemas.devices import DeviceRegistrationRequest, DeviceRegistrationResponse, UploadGuidance
from app.services.registry import DeviceRecord, InMemoryDeviceRegistry

logger = logging.getLogger("milli.devices")

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "/register",
    response_model=DeviceRegistrationResponse,
    summary="Register an authorized device",
    description=(
        "The device authenticates with `X-Device-ID` and `X-Device-Key`, which must match an entry in "
        "`MILLI_DEVICE_CREDENTIALS`. Calling it again updates the stored device information."
    ),
    responses=error_responses(401, 413, 422),
)
def register_device(
    payload: DeviceRegistrationRequest,
    request: Request,
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    registry: InMemoryDeviceRegistry = Depends(get_registry),
) -> DeviceRegistrationResponse:
    now = datetime.now(UTC)
    record, created = registry.register(
        DeviceRecord(
            device_id=device.device_id,
            firmware_version=payload.firmware_version,
            hardware_model=payload.hardware_model,
            camera_model=payload.camera_model,
            on_device_face_detection=payload.on_device_face_detection,
            registered_at=now,
        )
    )
    detector_name = request.app.state.capture_service.detector.name
    logger.info(
        "device %s device_id=%s firmware=%s hardware=%s on_device_detection=%s",
        "registered" if created else "re-registered",
        record.device_id, record.firmware_version, record.hardware_model, record.on_device_face_detection,
    )
    return DeviceRegistrationResponse(
        device_id=record.device_id,
        status="registered" if created else "updated",
        registered_at=record.registered_at,
        server_time=now,
        server_face_detector=detector_name,
        registration_persisted=registry.persistent,
        upload=UploadGuidance(
            endpoint="/api/v1/camera/capture",
            max_image_bytes=settings.max_image_bytes,
            allowed_image_formats=list(settings.allowed_formats),
            accepted_content_types=["multipart/form-data", "application/octet-stream", "image/*"],
            multipart_field="image",
        ),
    )
