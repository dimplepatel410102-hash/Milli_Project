"""Interfaces for planned Milli features, and the feature catalog served at /api/v1/features.

Face recognition and enrollment are implemented in app/services/recognition.py.
Nothing here returns data: no attendance records, check-ins or liveness results.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class RecognitionMatch:
    person_id: str
    similarity: float


@dataclass(frozen=True)
class LivenessResult:
    is_live: bool
    method: str
    score: float | None = None


class ConsentService(Protocol):
    """Records and checks a person's consent before any biometric data is enrolled or matched."""

    def record_consent(self, person_id: str, purpose: str, granted_at: datetime) -> str: ...
    def revoke_consent(self, person_id: str, purpose: str) -> None: ...
    def has_valid_consent(self, person_id: str, purpose: str) -> bool: ...


class EnrollmentService(Protocol):
    """Enrolls employees' faces. Implementations must require consent first."""

    def enroll(self, person_id: str, images: list[Image.Image]) -> str: ...
    def remove(self, person_id: str) -> None: ...


class FaceRecognitionService(Protocol):
    def identify(self, image: Image.Image) -> RecognitionMatch | None: ...


class LivenessService(Protocol):
    def check(self, frames: list[Image.Image]) -> LivenessResult: ...


class AttendanceService(Protocol):
    def record_event(self, person_id: str, device_id: str, event: str, at: datetime) -> str: ...


class VisitorService(Protocol):
    def register_visitor(self, name: str, host_person_id: str | None, arrived_at: datetime) -> str: ...


class AppointmentService(Protocol):
    def check_in(self, appointment_id: str, at: datetime) -> None: ...


class BusinessInfoService(Protocol):
    def get_info(self) -> dict[str, str]: ...


FEATURE_CATALOG: list[tuple[str, str, str]] = [
    ("health", "available", "GET /health"),
    ("device_registration", "available", "POST /api/v1/devices/register with per-device API keys; in-memory only."),
    ("image_capture", "available", "POST /api/v1/camera/capture with format detection and validation."),
    ("server_face_detection", "optional", "OpenCV Haar or YuNet detector via MILLI_FACE_DETECTOR; off by default."),
    ("device_reported_detection", "available", "Device detection results accepted via headers and passed through unverified."),
    ("temporary_image_storage", "optional", "Disabled by default; MILLI_STORE_IMAGES=true enables it."),
    ("consent_management", "placeholder", "Interface only (ConsentService)."),
    ("employee_enrollment", "optional", "POST /api/v1/faces/enroll stores SFace embeddings per employee ID; "
                                        "no consent workflow yet."),
    ("face_recognition", "optional", "OpenCV YuNet + SFace when MILLI_FACE_RECOGNITION=true; off by default."),
    ("liveness_check", "placeholder", "Interface only (LivenessService)."),
    ("attendance", "placeholder", "Interface only (AttendanceService)."),
    ("visitor_handling", "placeholder", "Interface only (VisitorService)."),
    ("appointment_check_in", "placeholder", "Interface only (AppointmentService)."),
    ("business_info_admin_panel", "placeholder", "Interface only (BusinessInfoService); no admin panel."),
]
