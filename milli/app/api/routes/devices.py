"""Device registration route."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Request, Response, Security

from app.api.deps import authorize_device, device_api_key
from app.core.logging import get_logger
from app.schemas.devices import DeviceRegisterRequest, DeviceRegisterResponse
from app.schemas.errors import ErrorResponse

logger = get_logger()

router = APIRouter(prefix="/devices", tags=["devices"])

_ERRORS = {
    401: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    responses=_ERRORS,
    summary="Register a configured device",
    description=(
        "Registers a device that is already listed in MILLI_DEVICE_CREDENTIALS. "
        "The server does not invent credentials. Send the API key in the X-Device-Key header. "
        "Registration is kept in memory and is cleared when the process stops."
    ),
)
def register_device(
    body: DeviceRegisterRequest,
    request: Request,
    response: Response,
    api_key: Annotated[str | None, Security(device_api_key)] = None,
) -> DeviceRegisterResponse:
    authorize_device(body.device_id, api_key, request.app.state.credentials)
    now = datetime.now(timezone.utc)
    record, created = request.app.state.registry.register(body.device_id, now)
    response.status_code = 201 if created else 200
    logger.info(
        "Device registered device_id=%s created=%s registered_at=%s status=registered",
        record.device_id,
        created,
        record.registered_at.isoformat(),
    )
    return DeviceRegisterResponse(
        device_id=record.device_id,
        registered=True,
        registered_at=record.registered_at,
        last_seen_at=record.last_seen_at,
        message="Device registered." if created else "Device registration refreshed.",
    )
