"""Face-detection interface.

Phase 1 ships a detector that does not run. It cannot return a face result.
Server-side detection and trusted on-device detection are separate
implementations that refuse the request until a real detector is added.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.errors import DetectionNotAvailable
from app.services.images import ValidatedImage

DetectionSource = Literal["server", "device"]


@dataclass(frozen=True)
class DeviceDetectionClaim:
    """Unverified report from the camera device. Not a detection result."""

    face_reported: bool


@dataclass(frozen=True)
class DetectionOutcome:
    performed: bool
    face_detected: bool | None
    source: DetectionSource | None
    message: str


class FaceDetector(Protocol):
    def evaluate(
        self,
        image: ValidatedImage,
        device_claim: DeviceDetectionClaim | None = None,
    ) -> DetectionOutcome:
        """Detect a face, or accept a future on-device result.

        ``device_claim`` is reserved for a future mode that explicitly trusts
        the ESP32 detector. Phase 1 does not turn that claim into ``face_detected``.
        """


class DisabledFaceDetector:
    """Accept the image and record that no detector ran."""

    def evaluate(
        self,
        image: ValidatedImage,
        device_claim: DeviceDetectionClaim | None = None,
    ) -> DetectionOutcome:
        del image, device_claim
        return DetectionOutcome(
            performed=False,
            face_detected=None,
            source=None,
            message="Image received and validated. Face detection was not performed.",
        )


class UnimplementedServerDetector:
    """Placeholder for a future server-side model. It never reports a face."""

    def evaluate(
        self,
        image: ValidatedImage,
        device_claim: DeviceDetectionClaim | None = None,
    ) -> DetectionOutcome:
        del image, device_claim
        raise DetectionNotAvailable(
            "Server-side face detection is not implemented. No detection result was produced.",
            received=False,
            face_detection_performed=False,
        )


class UnimplementedDeviceDetector:
    """Placeholder for a future trusted on-device result. It never reports a face."""

    def evaluate(
        self,
        image: ValidatedImage,
        device_claim: DeviceDetectionClaim | None = None,
    ) -> DetectionOutcome:
        del image, device_claim
        raise DetectionNotAvailable(
            "On-device face detection results are not accepted yet. No detection result was produced.",
            received=False,
            face_detection_performed=False,
        )


def build_detector(mode: str) -> FaceDetector:
    if mode == "disabled":
        return DisabledFaceDetector()
    if mode == "server":
        return UnimplementedServerDetector()
    if mode == "device":
        return UnimplementedDeviceDetector()
    raise ValueError(f"Unsupported face detection mode: {mode}")
