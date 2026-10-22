from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_SAFE_TEXT = r"^[A-Za-z0-9 ._+()/-]+$"


class DeviceRegistrationRequest(BaseModel):
    """Self-description sent by the device. Identity comes from the auth headers, not the body."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "firmware_version": "0.1.0",
                    "hardware_model": "ESP32-S3-N16R8",
                    "camera_model": None,
                    "on_device_face_detection": False,
                }
            ]
        },
    )

    firmware_version: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._+-]+$")
    hardware_model: str = Field(default="ESP32-S3-N16R8", min_length=1, max_length=64, pattern=_SAFE_TEXT)
    camera_model: str | None = Field(default=None, min_length=1, max_length=64, pattern=_SAFE_TEXT)
    on_device_face_detection: bool = Field(
        default=False, description="Whether the firmware runs its own face detection before uploading."
    )


class UploadGuidance(BaseModel):
    endpoint: str
    max_image_bytes: int
    allowed_image_formats: list[str]
    accepted_content_types: list[str]
    multipart_field: str


class DeviceRegistrationResponse(BaseModel):
    device_id: str
    status: str = Field(description="'registered' on first registration, 'updated' on re-registration.")
    registered_at: datetime
    server_time: datetime
    server_face_detector: str
    registration_persisted: bool = Field(
        description="False in Phase 1: registrations are kept in memory and lost on server restart."
    )
    upload: UploadGuidance
