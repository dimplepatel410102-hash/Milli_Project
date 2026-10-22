"""Shared response models."""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    loc: list[str]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    error: str = Field(description="Stable error code.")
    message: str = Field(description="Safe message. It does not include credentials or image bytes.")
    received: bool | None = Field(
        default=None,
        description="False when a capture was rejected. Omitted for errors that are not captures.",
    )
    face_detection_performed: bool | None = Field(
        default=None,
        description="False when a capture was rejected before detection. Omitted otherwise.",
    )
    details: list[ErrorDetail] | None = None
