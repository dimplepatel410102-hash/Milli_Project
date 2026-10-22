"""Server-side face detection, selected with MILLI_FACE_DETECTOR.

"none"         - default; no detection runs and responses say so.
"opencv_haar"  - OpenCV Haar cascade (optional dependency, requirements-detection.txt).
                 Real detection, but basic: frontal faces only, with false positives
                 and misses. Suitable for bench testing, not for access decisions.
"opencv_yunet" - OpenCV YuNet DNN detector (app/services/recognition.py). Needed for
                 face recognition, which aligns faces with YuNet's landmarks.

New detectors only need to implement the FaceDetector protocol.
"""

import threading
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class DetectedFace:
    x: int
    y: int
    width: int
    height: int
    confidence: float | None = None
    # Raw detector output used to align the face for recognition (YuNet: box, 5 landmarks, score).
    landmarks: tuple[float, ...] | None = None

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class DetectionOutcome:
    performed: bool
    detector: str | None
    faces: tuple[DetectedFace, ...] = field(default_factory=tuple)
    message: str = ""


class FaceDetector(Protocol):
    name: str

    def detect(self, image: Image.Image) -> DetectionOutcome: ...


class DetectorUnavailable(RuntimeError):
    pass


class DisabledFaceDetector:
    name = "none"

    def detect(self, image: Image.Image) -> DetectionOutcome:
        return DetectionOutcome(
            performed=False,
            detector=None,
            message="Server-side face detection is disabled (MILLI_FACE_DETECTOR=none); no detection was run.",
        )


class OpenCVHaarFaceDetector:
    name = "opencv_haar"

    def __init__(self, scale_factor: float = 1.1, min_neighbors: int = 5, min_face_px: int = 30) -> None:
        try:
            import cv2
            import numpy
        except ImportError as exc:
            raise DetectorUnavailable(
                "MILLI_FACE_DETECTOR=opencv_haar requires OpenCV. "
                "Install it with: pip install -r requirements-detection.txt"
            ) from exc

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            raise DetectorUnavailable(f"OpenCV Haar cascade could not be loaded from {cascade_path}")

        self._numpy = numpy
        self._cascade = cascade
        self._lock = threading.Lock()
        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = (min_face_px, min_face_px)

    def detect(self, image: Image.Image) -> DetectionOutcome:
        gray = self._numpy.asarray(image.convert("L"))
        with self._lock:
            rects = self._cascade.detectMultiScale(
                gray,
                scaleFactor=self._scale_factor,
                minNeighbors=self._min_neighbors,
                minSize=self._min_size,
            )
        faces = tuple(DetectedFace(int(x), int(y), int(w), int(h)) for x, y, w, h in rects)
        return DetectionOutcome(
            performed=True,
            detector=self.name,
            faces=faces,
            message=f"OpenCV Haar cascade ran and found {len(faces)} face(s).",
        )


def build_face_detector(name: str, model_dir: str = "models", min_confidence: float = 0.6) -> FaceDetector:
    if name == "none":
        return DisabledFaceDetector()
    if name == "opencv_haar":
        return OpenCVHaarFaceDetector()
    if name == "opencv_yunet":
        from app.services.recognition import YuNetFaceDetector

        return YuNetFaceDetector(model_dir, min_confidence)
    raise DetectorUnavailable(f"Unknown face detector '{name}'")
