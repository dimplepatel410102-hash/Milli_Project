"""Shared API dependencies."""

from fastapi.security import APIKeyHeader

from app.core.credentials import (
    DEVICE_ID_RE,
    MAX_API_KEY_LENGTH,
    authentication_failure_reason,
    credentials_match,
)
from app.core.errors import InvalidRequest, UnauthorizedDevice
from app.core.logging import get_logger

logger = get_logger()

device_api_key = APIKeyHeader(
    name="X-Device-Key",
    scheme_name="DeviceApiKey",
    auto_error=False,
    description="Per-device API key from server configuration. Send it only in this header.",
)


def require_device_id(value: str | None) -> str:
    if value is None or not value.strip():
        raise UnauthorizedDevice("Device credentials are required.")
    device_id = value.strip()
    if not DEVICE_ID_RE.fullmatch(device_id):
        raise InvalidRequest("device_id format is invalid.")
    return device_id


def authorize_device(device_id: str, api_key: str | None, credentials: dict[str, str]) -> None:
    """Accept the device only when its configured API key matches."""
    if api_key is None or not api_key.strip():
        logger.warning(
            "Device authentication failed device_id=%s reason=missing_key status=rejected",
            device_id,
        )
        raise UnauthorizedDevice("Device credentials are required.")

    provided = api_key.strip()
    if len(provided) > MAX_API_KEY_LENGTH or not credentials_match(device_id, provided, credentials):
        reason = (
            "key_rejected"
            if len(provided) > MAX_API_KEY_LENGTH
            else authentication_failure_reason(device_id, credentials)
        )
        logger.warning(
            "Device authentication failed device_id=%s reason=%s status=rejected",
            device_id,
            reason,
        )
        raise UnauthorizedDevice("Device credentials were rejected.")
