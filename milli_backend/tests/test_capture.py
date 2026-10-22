import os
import time

from app.services.detection import DetectedFace, DetectionOutcome
from app.services.storage import LocalImageStore
from tests.conftest import AUTH, CAPTURE_URL, DEVICE_ID, DEVICE_KEY, REGISTER_URL, error_code, image_bytes


def test_upload_accepts_registered_key_and_rejects_a_different_one(client):
    image = image_bytes("JPEG")
    accepted = client.post(CAPTURE_URL, content=image, headers=AUTH)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "received"
    assert DEVICE_KEY not in accepted.text

    rejected = client.post(
        CAPTURE_URL, content=image, headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "not-the-registered-key"}
    )
    assert rejected.status_code == 401
    assert error_code(rejected) == "unauthorized_device"
    assert "not-the-registered-key" not in rejected.text


def test_multipart_jpeg_upload(client):
    data = image_bytes("JPEG")
    response = client.post(CAPTURE_URL, files={"image": ("frame.jpg", data, "image/jpeg")}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["image_received"] is True
    assert body["device_id"] == DEVICE_ID
    assert body["image"] == {"format": "JPEG", "width": 64, "height": 48, "mode": "RGB", "size_bytes": len(data)}
    assert body["stored"] is False
    assert len(body["capture_id"]) == 32


def test_no_detection_claimed_when_detector_disabled(client):
    body = client.post(CAPTURE_URL, content=image_bytes("PNG"), headers=AUTH).json()

    assert body["face_detection_performed"] is False
    assert body["server_detection"]["performed"] is False
    assert body["server_detection"]["face_detected"] is None
    assert body["server_detection"]["face_count"] is None
    assert body["server_detection"]["faces"] == []
    assert body["device_detection"]["reported"] is False


def test_raw_body_upload_png(client):
    response = client.post(
        CAPTURE_URL,
        content=image_bytes("PNG"),
        headers={**AUTH, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200
    assert response.json()["image"]["format"] == "PNG"


def test_format_detected_from_bytes_not_content_type(client):
    response = client.post(
        CAPTURE_URL, content=image_bytes("BMP"), headers={**AUTH, "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 200
    assert response.json()["image"]["format"] == "BMP"


def test_raw_body_with_default_client_content_type(client):
    # esp_http_client and curl --data-binary send this Content-Type unless told otherwise.
    response = client.post(
        CAPTURE_URL,
        content=image_bytes("JPEG"),
        headers={**AUTH, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert response.json()["image"]["format"] == "JPEG"


def test_webp_upload(client):
    response = client.post(CAPTURE_URL, content=image_bytes("WEBP"), headers={**AUTH, "Content-Type": "image/webp"})
    assert response.status_code == 200
    assert response.json()["image"]["format"] == "WEBP"


def test_device_reported_detection_passed_through_unverified(client):
    headers = {
        **AUTH,
        "Content-Type": "image/jpeg",
        "X-Capture-Id": "seq-000123",
        "X-Captured-At": "2026-10-21T07:15:00Z",
        "X-Device-Face-Detected": "true",
        "X-Device-Face-Count": "1",
        "X-Device-Detector": "esp-dl",
    }
    body = client.post(CAPTURE_URL, content=image_bytes(), headers=headers).json()

    assert body["device_capture_id"] == "seq-000123"
    assert body["captured_at"].startswith("2026-10-21T07:15:00")
    assert body["device_detection"] == {
        "reported": True,
        "face_detected": True,
        "face_count": 1,
        "detector": "esp-dl",
        "verified_by_server": False,
    }
    assert body["face_detection_performed"] is False


def test_registration_required_when_configured(make_client):
    client = make_client(require_registration=True)

    blocked = client.post(CAPTURE_URL, content=image_bytes(), headers=AUTH)
    assert blocked.status_code == 403
    assert error_code(blocked) == "device_not_registered"

    client.post(REGISTER_URL, json={"firmware_version": "0.1.0"}, headers=AUTH)
    assert client.post(CAPTURE_URL, content=image_bytes(), headers=AUTH).status_code == 200


def test_server_detection_result_reported_when_detector_runs(make_client):
    class StubDetector:
        """Test double standing in for a real detector."""

        name = "stub"

        def detect(self, image):
            return DetectionOutcome(
                performed=True,
                detector=self.name,
                faces=(DetectedFace(1, 2, 10, 12, 0.9), DetectedFace(20, 5, 8, 8)),
                message="stub ran",
            )

    client = make_client(detector=StubDetector())
    body = client.post(CAPTURE_URL, content=image_bytes(), headers=AUTH).json()

    assert body["face_detection_performed"] is True
    detection = body["server_detection"]
    assert detection["detector"] == "stub"
    assert detection["face_detected"] is True
    assert detection["face_count"] == 2
    assert detection["faces"][0] == {"x": 1, "y": 2, "width": 10, "height": 12, "confidence": 0.9}


def test_server_detection_with_zero_faces(make_client):
    class NoFacesDetector:
        name = "stub"

        def detect(self, image):
            return DetectionOutcome(performed=True, detector=self.name, message="ran")

    body = make_client(detector=NoFacesDetector()).post(CAPTURE_URL, content=image_bytes(), headers=AUTH).json()

    assert body["face_detection_performed"] is True
    assert body["server_detection"]["face_detected"] is False
    assert body["server_detection"]["face_count"] == 0


def test_images_not_stored_by_default(make_client, tmp_path):
    client = make_client(storage_dir=tmp_path)
    body = client.post(CAPTURE_URL, content=image_bytes(), headers=AUTH).json()

    assert body["stored"] is False
    assert list(tmp_path.iterdir()) == []


def test_images_stored_when_enabled(make_client, tmp_path):
    client = make_client(store_images=True, storage_dir=tmp_path)
    data = image_bytes("PNG")
    body = client.post(CAPTURE_URL, content=data, headers=AUTH).json()

    assert body["stored"] is True
    files = list((tmp_path / DEVICE_ID).iterdir())
    assert len(files) == 1
    assert files[0].name.endswith(f"{body['capture_id']}.png")
    assert files[0].read_bytes() == data


def test_storage_prunes_expired_files(tmp_path):
    old = tmp_path / DEVICE_ID / "old.jpg"
    old.parent.mkdir()
    old.write_bytes(b"x")
    past = time.time() - 7200
    os.utime(old, (past, past))
    fresh = tmp_path / DEVICE_ID / "fresh.jpg"
    fresh.write_bytes(b"y")

    assert LocalImageStore(tmp_path, max_age_seconds=3600).prune() == 1
    assert not old.exists()
    assert fresh.exists()
