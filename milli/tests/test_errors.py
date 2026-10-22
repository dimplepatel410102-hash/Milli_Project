"""HTTP errors for authentication, invalid images, size limits, and processing failures."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import API_KEY, DEVICE_ID, PNG_1X1, device_headers, make_settings, register_device


def test_capture_requires_credentials(client):
    response = client.post("/api/v1/camera/capture")

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert body["received"] is False
    assert body["face_detection_performed"] is False


def test_capture_rejects_malformed_device_id(client):
    response = client.post(
        "/api/v1/camera/capture",
        headers={"X-Device-Id": "bad id", "X-Device-Key": API_KEY},
        content=PNG_1X1,
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "bad id" not in response.text


def test_capture_rejects_wrong_key(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(api_key="wrong-key-0123456789"),
        files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
    )

    assert response.status_code == 401
    assert response.json()["received"] is False
    assert "wrong-key-0123456789" not in response.text


def test_missing_image_field(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"photo": ("frame.png", PNG_1X1, "application/octet-stream")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "missing_image"
    assert body["received"] is False
    assert body["face_detection_performed"] is False


def test_empty_image_is_rejected(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("frame.png", b"", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "missing_image"


def test_non_image_bytes_are_rejected(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("notes.txt", b"this is not an image", "text/plain")},
    )

    assert response.status_code == 415
    body = response.json()
    assert body["error"] == "unsupported_image"
    assert body["received"] is False
    assert body["face_detection_performed"] is False
    assert "face_detected" not in body


def test_truncated_image_is_rejected(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers={**device_headers(), "Content-Type": "image/png"},
        content=b"\x89PNG\r\n\x1a\nnot-a-complete-image",
    )

    assert response.status_code == 415
    assert response.json()["face_detection_performed"] is False


def test_ppm_is_not_in_the_supported_set(client):
    from io import BytesIO

    from PIL import Image

    register_device(client)
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (9, 9, 9)).save(buffer, format="PPM")
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("frame.ppm", buffer.getvalue(), "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_image"


def test_unsupported_content_type(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers={**device_headers(), "Content-Type": "text/plain"},
        content=b"hello",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert response.json()["received"] is False


def test_invalid_device_face_flag(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
        data={"device_reported_face": "maybe"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "device_reported_face must be true or false."


def test_more_than_one_image_is_rejected(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files=[
            ("image", ("a.png", PNG_1X1, "application/octet-stream")),
            ("image", ("b.png", PNG_1X1, "application/octet-stream")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Send exactly one image."


def test_image_over_the_size_limit_is_rejected():
    app = create_app(make_settings(max_image_bytes=32))
    with TestClient(app) as client:
        register_device(client)
        response = client.post(
            "/api/v1/camera/capture",
            headers=device_headers(),
            files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
        )

    assert response.status_code == 413
    body = response.json()
    assert body["error"] == "payload_too_large"
    assert body["received"] is False
    assert body["face_detection_performed"] is False


def test_body_over_the_http_limit_is_rejected():
    app = create_app(make_settings(max_image_bytes=100))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/camera/capture",
            headers={**device_headers(), "Content-Type": "application/octet-stream"},
            content=b"x" * 9000,
        )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_server_detection_mode_does_not_invent_a_face():
    app = create_app(make_settings(face_detection_mode="server"))
    with TestClient(app) as client:
        assert register_device(client).status_code == 201
        response = client.post(
            "/api/v1/camera/capture",
            headers=device_headers(),
            files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
        )

    assert response.status_code == 501
    body = response.json()
    assert body["error"] == "detection_not_available"
    assert body["received"] is False
    assert body["face_detection_performed"] is False
    assert body.get("face_detected") is not True
    assert "not implemented" in body["message"].lower()


def test_processing_failure_hides_internal_details(app, client):
    class BoomDetector:
        def evaluate(self, image, device_claim=None):
            del image, device_claim
            raise RuntimeError("boom-secret-image")

    app.state.detector = BoomDetector()
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "processing_failed"
    assert body["message"] == "The image could not be processed."
    assert body["received"] is False
    assert body["face_detection_performed"] is False
    assert "boom-secret-image" not in response.text
    assert "Traceback" not in response.text


def test_images_are_not_stored_by_default(tmp_path, client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
        files={"image": ("frame.png", PNG_1X1, "application/octet-stream")},
    )

    assert response.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_temp_file_is_removed_unless_retention_is_enabled(tmp_path):
    app = create_app(
        make_settings(store_images=True, retain_temp_images=False, temp_dir=str(tmp_path))
    )
    with TestClient(app) as client:
        register_device(client)
        response = client.post(
            "/api/v1/camera/capture",
            headers=device_headers(),
            files={"image": ("../../secret.png", PNG_1X1, "application/octet-stream")},
        )

    assert response.status_code == 200
    assert response.json()["face_detected"] is None
    assert list(tmp_path.iterdir()) == []


def test_retained_temp_file_uses_the_capture_id(tmp_path):
    app = create_app(
        make_settings(store_images=True, retain_temp_images=True, temp_dir=str(tmp_path))
    )
    with TestClient(app) as client:
        register_device(client)
        response = client.post(
            "/api/v1/camera/capture",
            headers=device_headers(),
            files={"image": ("../../secret.png", PNG_1X1, "application/octet-stream")},
        )

    assert response.status_code == 200
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].name == f"{response.json()['capture_id']}.png"
    assert saved[0].read_bytes() == PNG_1X1
    assert "secret" not in saved[0].name
    assert response.json()["face_detection_performed"] is False


def test_unconfigured_devices_cannot_register():
    app = create_app(make_settings(device_credentials=""))
    with TestClient(app) as client:
        response = register_device(client)

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
