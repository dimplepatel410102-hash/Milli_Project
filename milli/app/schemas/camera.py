"""Capture response. face_detected stays null until a detector actually runs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaptureResponse(BaseModel):
    capture_id: str
    device_id: str
    received: bool = Field(description="True only after the image bytes were validated.")
    received_at: datetime = Field(description="Server time when the image was accepted.")
    image_bytes: int
    image_format: str = Field(description="Format identified from the image bytes.")
    face_detection_performed: bool = Field(
        description="True only when a face detector ran against this image."
    )
    face_detected: bool | None = Field(
        description=(
            "True or false only after a detector runs. "
            "Null means detection was not performed. "
            "A device report is not copied into this field."
        )
    )
    detection_source: Literal["server", "device"] | None = Field(
        description="Where a completed detection came from. Null when detection did not run."
    )
    device_reported_face: bool | None = Field(
        description="Unverified claim sent by the device. This is not a detection result."
    )
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "capture_id": "2f1c0c3e-0b1a-4f3a-9c2e-7a0b1c2d3e4f",
                "device_id": "dev-device-001",
                "received": True,
                "received_at": "2026-10-21T06:45:00Z",
                "image_bytes": 68,
                "image_format": "PNG",
                "face_detection_performed": False,
                "face_detected": None,
                "detection_source": None,
                "device_reported_face": None,
                "message": "Image received and validated. Face detection was not performed.",
            }
        }
    )
