import logging
from dataclasses import dataclass

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import Settings
from app.core.errors import DeviceNotRegistered, UnauthorizedDevice
from app.core.security import MAX_API_KEY_LENGTH, DeviceCredentialStore, is_valid_device_id
from app.services.capture import CaptureService
from app.services.registry import InMemoryDeviceRegistry

logger = logging.getLogger("milli.auth")

device_id_header = APIKeyHeader(
    name="X-Device-ID",
    scheme_name="DeviceId",
    description="Device identifier listed in MILLI_DEVICE_CREDENTIALS.",
    auto_error=False,
)
device_key_header = APIKeyHeader(
    name="X-Device-Key",
    scheme_name="DeviceKey",
    description="Per-device API key. Never logged.",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthenticatedDevice:
    device_id: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> InMemoryDeviceRegistry:
    return request.app.state.registry


def get_capture_service(request: Request) -> CaptureService:
    return request.app.state.capture_service


def authenticate_device(
    request: Request,
    device_id: str | None = Security(device_id_header),
    api_key: str | None = Security(device_key_header),
) -> AuthenticatedDevice:
    client = request.client.host if request.client else "-"
    if not device_id or not api_key:
        logger.warning("auth rejected reason=missing_credentials path=%s client=%s", request.url.path, client)
        raise UnauthorizedDevice("Missing X-Device-ID or X-Device-Key header.")

    store: DeviceCredentialStore = request.app.state.credentials
    valid_id = is_valid_device_id(device_id)
    if not valid_id or len(api_key) > MAX_API_KEY_LENGTH or not store.verify(device_id, api_key):
        logger.warning(
            "auth rejected reason=invalid_credentials device_id=%s path=%s client=%s",
            device_id if valid_id else "<malformed>", request.url.path, client,
        )
        raise UnauthorizedDevice()
    return AuthenticatedDevice(device_id=device_id)


def capture_device(
    device: AuthenticatedDevice = Depends(authenticate_device),
    settings: Settings = Depends(get_settings),
    registry: InMemoryDeviceRegistry = Depends(get_registry),
) -> AuthenticatedDevice:
    if settings.require_registration and registry.get(device.device_id) is None:
        logger.warning("capture rejected reason=not_registered device_id=%s", device.device_id)
        raise DeviceNotRegistered()
    return device
