"""Face enrollment and recognition.

The API tests use a fake detector/embedder (faces are fake: one per image, embedded
from the image colour) so they check the HTTP contract and matching logic quickly.
test_real_models_* run the actual YuNet + SFace models on real face photos.
"""

import io
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageEnhance, ImageOps

from app.factory import create_app
from app.services.detection import DetectedFace, DetectionOutcome
from app.services.recognition import FaceDatabase, FaceRecognizer
from tests.conftest import AUTH, CAPTURE_URL, error_code, make_settings

ENROLL_URL = "/api/v1/faces/enroll"
FACES_URL = "/api/v1/faces"
BACKEND_DIR = Path(__file__).resolve().parent.parent
FACE_PHOTOS = Path(__file__).resolve().parent / "face_photos"

RED, GREEN, BLUE = (220, 30, 30), (30, 220, 30), (30, 30, 220)


class FakeDetector:
    """No face in black images, two faces in images wider than 100 px, otherwise one."""

    name = "fake"

    def detect(self, image: Image.Image) -> DetectionOutcome:
        if image.convert("L").getextrema()[1] == 0:
            faces = ()
        else:
            count = 2 if image.width > 100 else 1
            faces = tuple(DetectedFace(0, 0, 10 + i, 10, 0.9, landmarks=(0.0,) * 15) for i in range(count))
        return DetectionOutcome(True, self.name, faces, "fake detector")


class FakeEmbedder:
    def embed(self, image: Image.Image, face: DetectedFace) -> list[float]:
        r, g, b = image.convert("RGB").getpixel((0, 0))
        norm = math.sqrt(r * r + g * g + b * b)
        return [r / norm, g / norm, b / norm]


def png(color: tuple[int, int, int], size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def recognizer(tmp_path) -> FaceRecognizer:
    return FaceRecognizer(FakeDetector(), FakeEmbedder(), FaceDatabase(tmp_path / "faces.json"), threshold=0.9)


@pytest.fixture
def client(recognizer, tmp_path) -> TestClient:
    settings = make_settings(store_images=True, storage_dir=tmp_path / "captures")
    return TestClient(create_app(settings, recognizer=recognizer))


def enroll(client, employee_id: str, color, **params):
    return client.post(ENROLL_URL, params={"employee_id": employee_id, **params}, content=png(color), headers=AUTH)


def recognition_of(client, color, size=(64, 48)) -> dict:
    response = client.post(CAPTURE_URL, content=png(color, size), headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()["recognition"]


def test_two_people_are_labelled_face_1_and_face_2_and_others_unknown(client):
    first = enroll(client, "E001", RED)
    second = enroll(client, "E002", GREEN)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["person"]["label"] == "Face 1"
    assert second.json()["person"]["label"] == "Face 2"

    face1 = recognition_of(client, (200, 40, 35))
    assert face1["status"] == "recognized"
    assert (face1["label"], face1["employee_id"]) == ("Face 1", "E001")
    assert face1["similarity"] >= face1["threshold"]
    assert face1["distance"] == pytest.approx(1 - face1["similarity"], abs=1e-3)

    face2 = recognition_of(client, (40, 200, 35))
    assert (face2["label"], face2["employee_id"]) == ("Face 2", "E002")

    unknown = recognition_of(client, BLUE)
    assert unknown["status"] == "unknown"
    assert unknown["label"] == "Unknown"
    assert unknown["employee_id"] is None
    assert unknown["similarity"] < unknown["threshold"]


def test_capture_without_face_does_not_invent_a_result(client):
    enroll(client, "E001", RED)
    result = recognition_of(client, (0, 0, 0))
    assert result["performed"] is True
    assert result["status"] == "no_face"
    assert result["label"] is None and result["employee_id"] is None


def test_capture_before_anyone_is_enrolled(client):
    result = recognition_of(client, RED)
    assert result["status"] == "no_enrolled_faces"
    assert result["label"] == "Unknown"


def test_recognition_disabled_by_default(make_client):
    client = make_client()
    body = client.post(CAPTURE_URL, content=png(RED), headers=AUTH).json()
    assert body["recognition"]["performed"] is False
    assert body["recognition"]["status"] == "disabled"
    response = client.post(ENROLL_URL, params={"employee_id": "E001"}, content=png(RED), headers=AUTH)
    assert response.status_code == 503
    assert error_code(response) == "recognition_disabled"


def test_enroll_rejects_images_without_exactly_one_face(client):
    no_face = enroll(client, "E001", (0, 0, 0))
    assert no_face.status_code == 422 and error_code(no_face) == "no_face_detected"

    two = client.post(ENROLL_URL, params={"employee_id": "E001"}, content=png(RED, (128, 48)), headers=AUTH)
    assert two.status_code == 422 and error_code(two) == "multiple_faces"


def test_enroll_requires_device_credentials_and_valid_ids(client):
    assert client.post(ENROLL_URL, params={"employee_id": "E001"}, content=png(RED)).status_code == 401
    bad = client.post(ENROLL_URL, params={"employee_id": "../x"}, content=png(RED), headers=AUTH)
    assert bad.status_code == 422


def test_custom_label_and_extra_samples(client):
    assert enroll(client, "E007", RED, label="Reception desk").json()["person"]["label"] == "Reception desk"
    again = enroll(client, "E007", (210, 40, 40)).json()["person"]
    assert again["samples"] == 2 and again["label"] == "Reception desk"


def test_enroll_from_stored_capture(client):
    capture_id = client.post(CAPTURE_URL, content=png(GREEN), headers=AUTH).json()["capture_id"]
    response = client.post(ENROLL_URL, params={"employee_id": "E002", "capture_id": capture_id}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert recognition_of(client, GREEN)["employee_id"] == "E002"

    missing = client.post(ENROLL_URL, params={"employee_id": "E003", "capture_id": "0" * 32}, headers=AUTH)
    assert missing.status_code == 404


def test_list_and_delete(client):
    enroll(client, "E001", RED)
    enroll(client, "E002", GREEN)
    listing = client.get(FACES_URL, headers=AUTH).json()
    assert listing["count"] == 2
    assert {p["employee_id"] for p in listing["people"]} == {"E001", "E002"}
    assert "embeddings" not in listing["people"][0]

    assert client.delete(f"{FACES_URL}/E001", headers=AUTH).json()["count"] == 1
    assert client.delete(f"{FACES_URL}/E001", headers=AUTH).status_code == 404
    assert recognition_of(client, RED)["label"] == "Unknown"


def test_database_persists_and_reuses_free_labels(tmp_path):
    path = tmp_path / "faces.json"
    db = FaceDatabase(path)
    db.add("E001", [1.0, 0.0])
    db.add("E002", [0.0, 1.0])
    db.remove("E001")
    assert db.add("E003", [0.6, 0.8]).label == "Face 1"

    reloaded = FaceDatabase(path)
    assert {p.employee_id: p.label for p in reloaded.people()} == {"E002": "Face 2", "E003": "Face 1"}
    match = reloaded.best_match([0.0, 1.0])
    assert match.person.employee_id == "E002" and match.similarity == pytest.approx(1.0)


# --- Real models on real photos -------------------------------------------------------------

def _real_recognizer(tmp_path) -> FaceRecognizer:
    pytest.importorskip("cv2")
    from app.services.detection import DetectorUnavailable
    from app.services.recognition import SFaceEmbedder, YuNetFaceDetector

    photos = [FACE_PHOTOS / name for name in ("person_a.jpg", "person_b.jpg", "person_c.jpg")]
    if not all(p.is_file() for p in photos):
        pytest.skip("face photos missing; run: python scripts/download_test_faces.py")
    try:
        detector = YuNetFaceDetector(BACKEND_DIR / "models", 0.6)
        embedder = SFaceEmbedder(BACKEND_DIR / "models")
    except DetectorUnavailable as exc:
        pytest.skip(str(exc))
    return FaceRecognizer(detector, embedder, FaceDatabase(tmp_path / "faces.json"), threshold=0.363)


def _variant(image: Image.Image) -> Image.Image:
    """A different-looking copy: mirrored, darker, lower resolution, re-encoded as JPEG."""
    changed = ImageEnhance.Brightness(ImageOps.mirror(image)).enhance(0.75)
    changed = changed.resize((changed.width * 2 // 3, changed.height * 2 // 3))
    buffer = io.BytesIO()
    changed.save(buffer, "JPEG", quality=70)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


def test_real_models_enroll_two_people_and_reject_a_third(tmp_path):
    recognizer = _real_recognizer(tmp_path)
    a, b, c = (Image.open(FACE_PHOTOS / f"person_{x}.jpg").convert("RGB") for x in "abc")

    assert recognizer.enroll(a, "E001").label == "Face 1"
    assert recognizer.enroll(b, "E002").label == "Face 2"

    for image, expected_label, expected_id in ((a, "Face 1", "E001"), (b, "Face 2", "E002")):
        probe = _variant(image)
        result = recognizer.identify(probe, recognizer.detector.detect(probe))
        assert result.status == "recognized", result.message
        assert (result.label, result.employee_id) == (expected_label, expected_id)

    result = recognizer.identify(c, recognizer.detector.detect(c))
    assert result.status == "unknown", result.message
    assert result.label == "Unknown" and result.employee_id is None
