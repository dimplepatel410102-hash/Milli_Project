"""Health response. Status means the process is up, not that a camera or a face is present."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="ok when this process can answer.")
    service: str
    version: str
    environment: str
    face_detection_mode: str = Field(
        description="disabled in Phase 1 means no face detector runs."
    )
