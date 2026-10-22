from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.errors import InvalidRequest


class DeviceCaptureMetadata(BaseModel):
    """Optional metadata the device sends as HTTP headers alongside the image."""

    device_capture_id: str | None = None
    captured_at: datetime | None = None
    face_detected: bool | None = None
    face_count: int | None = Field(default=None, ge=0, le=100)
    detector: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "DeviceCaptureMetadata":
        if self.face_detected is False and self.face_count:
            raise InvalidRequest("X-Device-Face-Count must be 0 when X-Device-Face-Detected is false.")
        if self.face_detected is None and (self.face_count is not None or self.detector):
            raise InvalidRequest(
                "X-Device-Face-Detected is required when sending X-Device-Face-Count or X-Device-Detector."
            )
        return self


class ImageInfo(BaseModel):
    format: str = Field(description="Format detected from the image bytes (not from Content-Type).")
    width: int
    height: int
    mode: str
    size_bytes: int


class FaceBox(BaseModel):
    x: int
    y: int
    width: int
    height: int
    confidence: float | None = None


class ServerFaceDetection(BaseModel):
    performed: bool = Field(description="True only if a server-side detector actually ran on this image.")
    detector: str | None
    face_detected: bool | None = Field(description="Null when detection was not performed.")
    face_count: int | None
    faces: list[FaceBox]
    message: str


class FaceRecognition(BaseModel):
    performed: bool = Field(description="True only if recognition actually ran on this image.")
    status: Literal["disabled", "no_face", "no_enrolled_faces", "recognized", "unknown"]
    label: str | None = Field(description='"Face 1", "Face 2", ... when recognized, "Unknown" when not.')
    employee_id: str | None = Field(description="Set only when an enrolled person was recognized.")
    similarity: float | None = Field(description="Cosine similarity to the best enrolled match (higher = closer).")
    distance: float | None = Field(description="1 - similarity.")
    threshold: float | None = Field(description="Minimum similarity for a match.")
    face: FaceBox | None = Field(description="The face that was recognized (the largest one).")
    message: str


class DeviceReportedDetection(BaseModel):
    reported: bool
    face_detected: bool | None
    face_count: int | None
    detector: str | None
    verified_by_server: bool = Field(
        default=False, description="Device-reported results are passed through, not verified."
    )


class CaptureResponse(BaseModel):
    capture_id: str
    device_id: str
    status: Literal["received"]
    image_received: bool
    face_detection_performed: bool = Field(
        description="Whether server-side face detection ran. Device-reported results do not count."
    )
    received_at: datetime
    captured_at: datetime | None
    device_capture_id: str | None
    image: ImageInfo
    server_detection: ServerFaceDetection
    recognition: FaceRecognition
    device_detection: DeviceReportedDetection
    stored: bool = Field(description="Whether the image was written to temporary storage.")
