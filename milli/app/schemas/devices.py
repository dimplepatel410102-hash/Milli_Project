"""Device registration models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.credentials import DEVICE_ID_RE


class DeviceRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(description="Device id that is already listed in server configuration.")

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError(
                "device_id must be 1-64 characters: letters, digits, '.', '_' or '-'."
            )
        return value


class DeviceRegisterResponse(BaseModel):
    device_id: str
    registered: bool
    registered_at: datetime
    last_seen_at: datetime
    message: str
