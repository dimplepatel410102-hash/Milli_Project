"""Server-side face recognition with OpenCV: YuNet detects and aligns, SFace embeds.

Enabled with MILLI_FACE_RECOGNITION=true. Enrolled people are stored as SFace
embeddings (not images) in MILLI_FACE_DB_PATH, a JSON file. Embeddings are
biometric data: keep the file private and delete people who withdraw consent.

A face matches an enrolled person when the cosine similarity of their
embeddings reaches MILLI_FACE_MATCH_THRESHOLD (0.363 is the SFace authors'
recommended cosine threshold). Below it, the face is reported as "Unknown".
"""

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image

from app.core.errors import MultipleFacesDetected, NoFaceDetected, RecognitionDisabled
from app.services.detection import DetectedFace, DetectionOutcome, DetectorUnavailable

logger = logging.getLogger("milli.recognition")

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = "face_recognition_sface_2021dec.onnx"
UNKNOWN_LABEL = "Unknown"
_AUTO_LABEL = re.compile(r"^Face (\d+)$")

RecognitionStatus = Literal["disabled", "no_face", "no_enrolled_faces", "recognized", "unknown"]


def _load_cv2():
    try:
        import cv2
        import numpy
    except ImportError as exc:
        raise DetectorUnavailable(
            "Face recognition requires OpenCV. Install it with: pip install -r requirements-detection.txt"
        ) from exc
    return cv2, numpy


def _model_path(model_dir: Path, name: str) -> str:
    path = Path(model_dir) / name
    if not path.is_file():
        raise DetectorUnavailable(
            f"Model file {path} is missing. Download it with: python scripts/download_models.py"
        )
    return str(path)


def _to_bgr(image: Image.Image):
    _, numpy = _load_cv2()
    return numpy.ascontiguousarray(numpy.asarray(image.convert("RGB"))[:, :, ::-1])


class YuNetFaceDetector:
    """OpenCV YuNet face detector. Returns landmarks so SFace can align each face."""

    name = "opencv_yunet"

    def __init__(self, model_dir: str | Path, min_confidence: float = 0.6) -> None:
        cv2, _ = _load_cv2()
        try:
            self._detector = cv2.FaceDetectorYN.create(
                _model_path(Path(model_dir), YUNET_MODEL), "", (320, 240), min_confidence, 0.3, 5000
            )
        except cv2.error as exc:
            raise DetectorUnavailable(f"YuNet model could not be loaded: {exc}") from exc
        self._lock = threading.Lock()
        self.min_confidence = min_confidence

    def detect(self, image: Image.Image) -> DetectionOutcome:
        bgr = _to_bgr(image)
        height, width = bgr.shape[:2]
        with self._lock:
            self._detector.setInputSize((width, height))
            _, rows = self._detector.detect(bgr)
        faces = []
        for row in rows if rows is not None else []:
            x, y, w, h = (int(round(v)) for v in row[:4])
            faces.append(
                DetectedFace(
                    x=max(x, 0), y=max(y, 0), width=w, height=h,
                    confidence=round(float(row[14]), 3),
                    landmarks=tuple(float(v) for v in row),
                )
            )
        return DetectionOutcome(
            performed=True,
            detector=self.name,
            faces=tuple(faces),
            message=f"OpenCV YuNet ran and found {len(faces)} face(s) at confidence >= {self.min_confidence}.",
        )


class FaceEmbedder(Protocol):
    def embed(self, image: Image.Image, face: DetectedFace) -> list[float]: ...


class SFaceEmbedder:
    """OpenCV SFace: aligns a YuNet face and returns an L2-normalised 128-value embedding."""

    def __init__(self, model_dir: str | Path) -> None:
        cv2, numpy = _load_cv2()
        try:
            self._recognizer = cv2.FaceRecognizerSF.create(_model_path(Path(model_dir), SFACE_MODEL), "")
        except cv2.error as exc:
            raise DetectorUnavailable(f"SFace model could not be loaded (corrupt download?): {exc}") from exc
        self._numpy = numpy
        self._lock = threading.Lock()

    def embed(self, image: Image.Image, face: DetectedFace) -> list[float]:
        if face.landmarks is None or len(face.landmarks) < 15:
            raise ValueError("SFace needs YuNet landmarks to align the face")
        row = self._numpy.asarray(face.landmarks, dtype=self._numpy.float32).reshape(1, -1)
        with self._lock:
            aligned = self._recognizer.alignCrop(_to_bgr(image), row)
            feature = self._recognizer.feature(aligned).flatten()
        norm = float(self._numpy.linalg.norm(feature))
        if norm == 0.0:
            raise ValueError("SFace returned an all-zero embedding")
        return [float(v) / norm for v in feature]


@dataclass
class EnrolledPerson:
    employee_id: str
    label: str
    enrolled_at: str
    embeddings: list[list[float]]


@dataclass(frozen=True)
class Match:
    person: EnrolledPerson
    similarity: float


class FaceDatabase:
    """Enrolled people in a JSON file, written atomically after every change."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._people: dict[str, EnrolledPerson] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("people", []):
                person = EnrolledPerson(**item)
                self._people[person.employee_id] = person

    def people(self) -> list[EnrolledPerson]:
        with self._lock:
            return list(self._people.values())

    def __len__(self) -> int:
        return len(self._people)

    def add(self, employee_id: str, embedding: list[float], label: str | None = None) -> EnrolledPerson:
        """Enroll a new person, or add another sample to an existing one."""
        with self._lock:
            person = self._people.get(employee_id)
            if person is None:
                person = EnrolledPerson(
                    employee_id=employee_id,
                    label=label or self._next_auto_label(),
                    enrolled_at=datetime.now(UTC).isoformat(),
                    embeddings=[],
                )
                self._people[employee_id] = person
            elif label:
                person.label = label
            person.embeddings.append(embedding)
            self._save()
            return person

    def remove(self, employee_id: str) -> bool:
        with self._lock:
            if self._people.pop(employee_id, None) is None:
                return False
            self._save()
            return True

    def best_match(self, embedding: list[float]) -> Match | None:
        best: Match | None = None
        with self._lock:
            for person in self._people.values():
                for sample in person.embeddings:
                    similarity = sum(a * b for a, b in zip(sample, embedding, strict=True))
                    if best is None or similarity > best.similarity:
                        best = Match(person, similarity)
        return best

    def _next_auto_label(self) -> str:
        used = {int(m.group(1)) for p in self._people.values() if (m := _AUTO_LABEL.match(p.label))}
        number = 1
        while number in used:
            number += 1
        return f"Face {number}"

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "people": [vars(p) for p in self._people.values()]}
        partial = self.path.with_suffix(self.path.suffix + ".part")
        partial.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(partial, self.path)


@dataclass(frozen=True)
class RecognitionResult:
    performed: bool
    status: RecognitionStatus
    message: str
    label: str | None = None
    employee_id: str | None = None
    similarity: float | None = None
    threshold: float | None = None
    face: DetectedFace | None = None

    @property
    def distance(self) -> float | None:
        return None if self.similarity is None else round(1.0 - self.similarity, 4)


class FaceRecognizer:
    def __init__(self, detector: YuNetFaceDetector, embedder: FaceEmbedder, database: FaceDatabase,
                 threshold: float) -> None:
        self.detector = detector
        self.embedder = embedder
        self.database = database
        self.threshold = threshold
        self.enabled = True

    def identify(self, image: Image.Image, detection: DetectionOutcome) -> RecognitionResult:
        """Recognize the largest face found by `detection` (which must come from self.detector)."""
        if not detection.faces:
            return RecognitionResult(True, "no_face", "No face was found, so recognition did not run.")
        face = max(detection.faces, key=lambda f: f.area)
        if len(self.database) == 0:
            return RecognitionResult(
                True, "no_enrolled_faces", "No people are enrolled yet; enroll with POST /api/v1/faces/enroll.",
                label=UNKNOWN_LABEL, threshold=self.threshold, face=face,
            )
        match = self.database.best_match(self.embedder.embed(image, face))
        similarity = round(match.similarity, 4)
        if similarity >= self.threshold:
            return RecognitionResult(
                True, "recognized",
                f"Matched {match.person.label} (similarity {similarity:.3f} >= {self.threshold}).",
                label=match.person.label, employee_id=match.person.employee_id,
                similarity=similarity, threshold=self.threshold, face=face,
            )
        return RecognitionResult(
            True, "unknown",
            f"No enrolled person matched (best similarity {similarity:.3f} < {self.threshold}).",
            label=UNKNOWN_LABEL, similarity=similarity, threshold=self.threshold, face=face,
        )

    def enroll(self, image: Image.Image, employee_id: str, label: str | None = None) -> EnrolledPerson:
        detection = self.detector.detect(image)
        if not detection.faces:
            raise NoFaceDetected("No face was detected in the enrollment image.")
        if len(detection.faces) > 1:
            raise MultipleFacesDetected(
                f"{len(detection.faces)} faces were detected; the enrollment image must show exactly one person."
            )
        return self.database.add(employee_id, self.embedder.embed(image, detection.faces[0]), label)


class DisabledFaceRecognizer:
    enabled = False
    threshold = None

    def identify(self, image: Image.Image, detection: DetectionOutcome) -> RecognitionResult:
        return RecognitionResult(
            False, "disabled", "Face recognition is disabled (MILLI_FACE_RECOGNITION=false); it did not run."
        )

    def enroll(self, image: Image.Image, employee_id: str, label: str | None = None) -> EnrolledPerson:
        raise RecognitionDisabled()

    @property
    def database(self) -> FaceDatabase:
        raise RecognitionDisabled()
