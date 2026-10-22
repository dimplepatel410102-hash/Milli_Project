"""Capture pipeline: validate, optionally keep a temp file, then ask the detector.

Image bytes are not logged. Temporary files are removed unless retention is enabled
and the capture completes.
"""

import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.errors import MilliError, ProcessingFailed
from app.core.logging import get_logger, safe_error_text
from app.services.detection import (
    DetectionOutcome,
    DeviceDetectionClaim,
    FaceDetector,
)
from app.services.images import ValidatedImage, validate_image

logger = get_logger()


@dataclass(frozen=True)
class CaptureResult:
    capture_id: str
    device_id: str
    received: bool
    received_at: datetime
    image_bytes: int
    image_format: str
    face_detection_performed: bool
    face_detected: bool | None
    detection_source: str | None
    device_reported_face: bool | None
    message: str


def process_capture(
    *,
    settings: Settings,
    detector: FaceDetector,
    device_id: str,
    image_bytes: bytes,
    device_reported_face: bool | None,
) -> CaptureResult:
    capture_id = str(uuid.uuid4())
    received_at = datetime.now(timezone.utc)
    image = validate_image(image_bytes)
    temp_path = _store_temp(settings, capture_id, image)
    claim = (
        None
        if device_reported_face is None
        else DeviceDetectionClaim(face_reported=device_reported_face)
    )
    try:
        outcome = _evaluate(detector, image, claim, device_id, capture_id)
        message = _message(outcome, device_reported_face)
        result = CaptureResult(
            capture_id=capture_id,
            device_id=device_id,
            received=True,
            received_at=received_at,
            image_bytes=image.byte_count,
            image_format=image.image_format,
            face_detection_performed=outcome.performed,
            face_detected=outcome.face_detected if outcome.performed else None,
            detection_source=outcome.source if outcome.performed else None,
            device_reported_face=device_reported_face,
            message=message,
        )
    except Exception:
        _discard_temp(temp_path)
        raise
    else:
        if temp_path is not None and not settings.retain_temp_images:
            _discard_temp(temp_path)
        elif temp_path is not None:
            logger.info(
                "Temporary image retained device_id=%s capture_id=%s path=%s",
                device_id,
                capture_id,
                temp_path,
            )

    logger.info(
        "Capture accepted device_id=%s capture_id=%s received_at=%s "
        "image_bytes=%s image_format=%s face_detection_performed=%s status=accepted",
        device_id,
        capture_id,
        received_at.isoformat(),
        image.byte_count,
        image.image_format,
        result.face_detection_performed,
    )
    return result


def _evaluate(
    detector: FaceDetector,
    image: ValidatedImage,
    claim: DeviceDetectionClaim | None,
    device_id: str,
    capture_id: str,
) -> DetectionOutcome:
    try:
        outcome = detector.evaluate(image, claim)
    except MilliError:
        raise
    except Exception as exc:
        logger.error(
            "Capture processing failed device_id=%s capture_id=%s status=error error=%s",
            device_id,
            capture_id,
            safe_error_text(exc),
        )
        raise ProcessingFailed(
            "The image could not be processed.",
            received=False,
            face_detection_performed=False,
        ) from exc
    if outcome.performed and outcome.face_detected is None:
        logger.error(
            "Detector reported completion without a result device_id=%s capture_id=%s status=error",
            device_id,
            capture_id,
        )
        raise ProcessingFailed(
            "The image could not be processed.",
            received=False,
            face_detection_performed=False,
        )
    if not outcome.performed:
        # A disabled detector must not smuggle a face boolean through this flag.
        return DetectionOutcome(
            performed=False,
            face_detected=None,
            source=None,
            message=outcome.message,
        )
    return outcome


def _message(outcome: DetectionOutcome, device_reported_face: bool | None) -> str:
    message = outcome.message
    if device_reported_face is True and not outcome.performed:
        message += " The device reported a face; that report was not verified and is not a detection result."
    return message


def _store_temp(settings: Settings, capture_id: str, image: ValidatedImage) -> Path | None:
    if not settings.store_images:
        return None
    directory = Path(settings.temp_dir) if settings.temp_dir else Path(tempfile.gettempdir()) / "milli"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{capture_id}{image.extension}"
    path.write_bytes(image.content)
    return path


def _discard_temp(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            "Temporary image could not be removed capture_id=%s error=%s",
            path.stem,
            safe_error_text(exc),
        )
    else:
        logger.info("Temporary image discarded capture_id=%s", path.stem)
