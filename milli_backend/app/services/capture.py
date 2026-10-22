"""Capture pipeline: validate image -> optional server-side detection and recognition -> optional storage.

Runs synchronously; API routes call it in a worker thread so image decoding
does not block the event loop.
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from app.core.errors import ProcessingFailed
from app.schemas.camera import (
    CaptureResponse,
    DeviceCaptureMetadata,
    DeviceReportedDetection,
    FaceBox,
    FaceRecognition,
    ImageInfo,
    ServerFaceDetection,
)
from app.services.detection import DetectedFace, DetectionOutcome, FaceDetector
from app.services.images import ImageValidator
from app.services.recognition import DisabledFaceRecognizer, FaceRecognizer, RecognitionResult
from app.services.registry import InMemoryDeviceRegistry
from app.services.storage import ImageStore

logger = logging.getLogger("milli.capture")


class CaptureService:
    def __init__(
        self,
        validator: ImageValidator,
        detector: FaceDetector,
        store: ImageStore,
        registry: InMemoryDeviceRegistry,
        recognizer: FaceRecognizer | DisabledFaceRecognizer | None = None,
    ) -> None:
        self.validator = validator
        self.detector = detector
        self.store = store
        self.registry = registry
        self.recognizer = recognizer or DisabledFaceRecognizer()

    def process(self, *, device_id: str, data: bytes, metadata: DeviceCaptureMetadata) -> CaptureResponse:
        started = time.perf_counter()
        received_at = datetime.now(UTC)
        capture_id = uuid.uuid4().hex

        image = self.validator.validate(data)

        try:
            outcome = self.detector.detect(image.image)
        except Exception as exc:
            logger.error(
                "face detection failed device_id=%s capture_id=%s detector=%s error=%s",
                device_id, capture_id, self.detector.name, type(exc).__name__,
            )
            raise ProcessingFailed(
                "The image was received but server-side face detection failed."
            ) from exc

        try:
            recognition = self.recognizer.identify(image.image, outcome)
        except Exception as exc:
            logger.error(
                "face recognition failed device_id=%s capture_id=%s error=%s: %s",
                device_id, capture_id, type(exc).__name__, exc,
            )
            raise ProcessingFailed("The image was received but face recognition failed.") from exc

        try:
            stored = self.store.save(
                device_id=device_id, capture_id=capture_id, image=image, received_at=received_at
            )
        except OSError as exc:
            logger.error(
                "image storage failed device_id=%s capture_id=%s error=%s",
                device_id, capture_id, type(exc).__name__,
            )
            raise ProcessingFailed("The image was received but could not be stored.") from exc

        self.registry.mark_capture(device_id, received_at)

        logger.info(
            "capture accepted device_id=%s capture_id=%s device_capture_id=%s captured_at=%s received_at=%s "
            "format=%s size_bytes=%d dimensions=%dx%d device_faces=%s server_faces=%s recognition=%s label=%s "
            "employee_id=%s similarity=%s stored=%s duration_ms=%.1f",
            device_id, capture_id, metadata.device_capture_id or "-",
            metadata.captured_at.isoformat() if metadata.captured_at else "-", received_at.isoformat(),
            image.format, image.size_bytes, image.width, image.height,
            metadata.face_count if metadata.face_count is not None else "-",
            len(outcome.faces) if outcome.performed else "-",
            recognition.status, recognition.label or "-", recognition.employee_id or "-",
            recognition.similarity if recognition.similarity is not None else "-",
            stored, (time.perf_counter() - started) * 1000,
        )

        return CaptureResponse(
            capture_id=capture_id,
            device_id=device_id,
            status="received",
            image_received=True,
            face_detection_performed=outcome.performed,
            received_at=received_at,
            captured_at=metadata.captured_at,
            device_capture_id=metadata.device_capture_id,
            image=ImageInfo(
                format=image.format,
                width=image.width,
                height=image.height,
                mode=image.mode,
                size_bytes=image.size_bytes,
            ),
            server_detection=_server_detection(outcome),
            recognition=_recognition(recognition),
            device_detection=DeviceReportedDetection(
                reported=metadata.face_detected is not None,
                face_detected=metadata.face_detected,
                face_count=metadata.face_count,
                detector=metadata.detector,
            ),
            stored=stored,
        )


def _face_box(face: DetectedFace) -> FaceBox:
    return FaceBox(x=face.x, y=face.y, width=face.width, height=face.height, confidence=face.confidence)


def _server_detection(outcome: DetectionOutcome) -> ServerFaceDetection:
    if not outcome.performed:
        return ServerFaceDetection(
            performed=False,
            detector=None,
            face_detected=None,
            face_count=None,
            faces=[],
            message=outcome.message,
        )
    return ServerFaceDetection(
        performed=True,
        detector=outcome.detector,
        face_detected=len(outcome.faces) > 0,
        face_count=len(outcome.faces),
        faces=[_face_box(f) for f in outcome.faces],
        message=outcome.message,
    )


def _recognition(result: RecognitionResult) -> FaceRecognition:
    return FaceRecognition(
        performed=result.performed,
        status=result.status,
        label=result.label,
        employee_id=result.employee_id,
        similarity=result.similarity,
        distance=result.distance,
        threshold=result.threshold,
        face=_face_box(result.face) if result.face else None,
        message=result.message,
    )
