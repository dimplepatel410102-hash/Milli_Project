"""Upload validation and error handling for /api/v1/camera/capture."""

import logging

import pytest

from tests.conftest import AUTH, CAPTURE_URL, DEVICE_ID, DEVICE_KEY, error_code, image_bytes


def test_capture_requires_credentials(client):
    response = client.post(CAPTURE_URL, content=image_bytes())
    assert response.status_code == 401
    assert error_code(response) == "unauthorized_device"


def test_capture_rejects_wrong_key(client):
    response = client.post(CAPTURE_URL, content=image_bytes(), headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "nope"})
    assert response.status_code == 401


def test_empty_raw_body(client):
    response = client.post(CAPTURE_URL, content=b"", headers={**AUTH, "Content-Type": "image/jpeg"})
    assert response.status_code == 400
    assert error_code(response) == "missing_image"


def test_multipart_without_image_field(client):
    response = client.post(CAPTURE_URL, files={"photo": ("a.jpg", image_bytes(), "image/jpeg")}, headers=AUTH)
    assert response.status_code == 400
    assert error_code(response) == "missing_image"


def test_multipart_image_field_not_a_file(client):
    response = client.post(CAPTURE_URL, data={"image": "hello"}, files={"x": ("x", b"x")}, headers=AUTH)
    assert response.status_code == 400
    assert error_code(response) == "invalid_request"


def test_multipart_empty_file(client):
    response = client.post(CAPTURE_URL, files={"image": ("a.jpg", b"", "image/jpeg")}, headers=AUTH)
    assert response.status_code == 400
    assert error_code(response) == "missing_image"


def test_multipart_multiple_files_rejected(client):
    files = [("image", ("a.jpg", image_bytes(), "image/jpeg")), ("image", ("b.jpg", image_bytes(), "image/jpeg"))]
    response = client.post(CAPTURE_URL, files=files, headers=AUTH)
    assert response.status_code == 400


def test_json_body_rejected(client):
    response = client.post(CAPTURE_URL, json={"image": "base64..."}, headers=AUTH)
    assert response.status_code == 415
    assert error_code(response) == "unsupported_image"


def test_non_image_bytes(client):
    response = client.post(
        CAPTURE_URL, content=b"definitely not an image" * 10, headers={**AUTH, "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 415
    assert error_code(response) == "unsupported_image"


def test_disallowed_format(client):
    response = client.post(CAPTURE_URL, content=image_bytes("GIF"), headers=AUTH)
    assert response.status_code == 415
    assert "JPEG" in response.json()["error"]["message"]


def test_allowed_formats_are_configurable(make_client):
    client = make_client(allowed_image_formats="GIF")
    assert client.post(CAPTURE_URL, content=image_bytes("GIF"), headers=AUTH).status_code == 200
    assert client.post(CAPTURE_URL, content=image_bytes("JPEG"), headers=AUTH).status_code == 415


def test_truncated_image(client):
    data = image_bytes("JPEG", size=(320, 240))
    response = client.post(CAPTURE_URL, content=data[: len(data) // 2], headers=AUTH)
    assert response.status_code == 422
    assert error_code(response) == "invalid_image"


def test_too_many_pixels(make_client):
    client = make_client(max_image_pixels=1000)
    response = client.post(CAPTURE_URL, content=image_bytes(size=(64, 48)), headers=AUTH)
    assert response.status_code == 422
    assert "pixel limit" in response.json()["error"]["message"]


def test_image_over_byte_limit(make_client):
    client = make_client(max_image_bytes=1024)
    response = client.post(CAPTURE_URL, content=image_bytes("BMP", size=(64, 48)), headers=AUTH)
    assert response.status_code == 413
    assert error_code(response) == "payload_too_large"


def test_request_over_declared_size_rejected_early(make_client):
    client = make_client(max_image_bytes=1024)
    response = client.post(CAPTURE_URL, content=b"\0" * (200 * 1024), headers=AUTH)
    assert response.status_code == 413
    assert error_code(response) == "payload_too_large"


def test_chunked_request_over_size_rejected(make_client):
    client = make_client(max_image_bytes=1024)

    def chunks():
        for _ in range(100):
            yield b"\0" * 4096

    response = client.post(CAPTURE_URL, content=chunks(), headers=AUTH)
    assert response.status_code == 413
    assert error_code(response) == "payload_too_large"


def test_oversized_json_on_register_rejected(make_client):
    client = make_client(max_image_bytes=1024)
    response = client.post(
        "/api/v1/devices/register",
        content=b'{"firmware_version": "' + b"a" * (200 * 1024) + b'"}',
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Device-Face-Count": "-1", "X-Device-Face-Detected": "true"},
        {"X-Device-Face-Detected": "maybe"},
        {"X-Captured-At": "yesterday"},
        {"X-Capture-Id": "bad id with spaces"},
    ],
    ids=["negative-count", "bad-bool", "bad-timestamp", "bad-capture-id"],
)
def test_invalid_metadata_headers(client, headers):
    response = client.post(CAPTURE_URL, content=image_bytes(), headers={**AUTH, **headers})
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_inconsistent_device_detection_headers(client):
    headers = {**AUTH, "X-Device-Face-Detected": "false", "X-Device-Face-Count": "2"}
    response = client.post(CAPTURE_URL, content=image_bytes(), headers=headers)
    assert response.status_code == 400
    assert error_code(response) == "invalid_request"


def test_detector_failure_returns_processing_error(make_client):
    class BrokenDetector:
        name = "broken"

        def detect(self, image):
            raise RuntimeError("model crashed")

    response = make_client(detector=BrokenDetector()).post(CAPTURE_URL, content=image_bytes(), headers=AUTH)

    assert response.status_code == 500
    assert error_code(response) == "processing_failed"
    assert "model crashed" not in response.text


def test_storage_failure_returns_processing_error(make_client, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    client = make_client(store_images=True, storage_dir=blocker)

    response = client.post(CAPTURE_URL, content=image_bytes(), headers=AUTH)

    assert response.status_code == 500
    assert error_code(response) == "processing_failed"


def test_logs_include_device_and_status_but_never_credentials(client, caplog):
    caplog.set_level(logging.INFO, logger="milli")
    image = image_bytes()

    client.post(CAPTURE_URL, content=image, headers=AUTH)
    client.post(CAPTURE_URL, content=image, headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "wrong-secret-xyz"})
    client.post(CAPTURE_URL, content=b"not an image", headers=AUTH)

    text = caplog.text
    assert f"capture accepted device_id={DEVICE_ID}" in text
    assert "received_at=" in text
    assert "auth rejected reason=invalid_credentials" in text
    assert "capture rejected" in text and "code=unsupported_image" in text
    assert DEVICE_KEY not in text
    assert "wrong-secret-xyz" not in text
    assert "not an image" not in text
