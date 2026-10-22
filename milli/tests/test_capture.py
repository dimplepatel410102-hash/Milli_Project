"""Image upload validation, capture status, and storage behavior."""

import io
import logging

from PIL import Image
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.detection import (
    DeviceDetectionClaim,
    DisabledFaceDetector,
    UnimplementedDeviceDetector,
    UnimplementedServerDetector,
)
from app.services.images import ValidatedImage
from tests.conftest import API_KEY, DEVICE_ID, PNG_1X1, device_headers, make_settings, register_device


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _bmp_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(buffer, format="BMP")
    return buffer.getvalue()


def _ppm_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (9, 9, 9)).save(buffer, format="PPM")
    return buffer.getvalue()


def _capture(client, content, filename="frame.bin", content_type="application/octet-stream", data=None, headers=None):
    return client.post(
        "/api/v1/camera/capture",
        headers=headers or device_headers(),
        files={"image": (filename, content, content_type)},
        data=data or {},
    )


def test_multipart_png_is_accepted_without_detection(client, caplog):
    assert register_device(client).status_code == 201

    with caplog.at_level(logging.INFO, logger="milli"):
        response = _capture(client, PNG_1X1, filename="../../secret.png", content_type="image/jpeg")

    assert response.status_code == 200
    body = response.json()
    assert body["received"] is True
    assert body["device_id"] == DEVICE_ID
    assert body["image_format"] == "PNG"
    assert body["image_bytes"] == len(PNG_1X1)
    assert body["face_detection_performed"] is False
    assert body["face_detected"] is None
    assert body["detection_source"] is None
    assert body["device_reported_face"] is None
    assert body["capture_id"]
    assert "Face detection was not performed" in body["message"]
    assert API_KEY not in response.text
    assert API_KEY not in caplog.text
    assert PNG_1X1.hex() not in caplog.text
    assert DEVICE_ID in caplog.text
    assert "status=accepted" in caplog.text


def test_raw_jpeg_bytes_are_accepted(client):
    register_device(client)
    jpeg = _jpeg_bytes()
    response = client.post(
        "/api/v1/camera/capture",
        headers={**device_headers(), "Content-Type": "application/octet-stream"},
        content=jpeg,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["received"] is True
    assert body["image_format"] == "JPEG"
    assert body["face_detection_performed"] is False
    assert body["face_detected"] is None


def test_bmp_upload_is_accepted(client):
    register_device(client)
    response = _capture(client, _bmp_bytes(), filename="frame.bmp")

    assert response.status_code == 200
    assert response.json()["image_format"] == "BMP"
    assert response.json()["face_detected"] is None


def test_device_face_report_is_not_treated_as_detection(client):
    register_device(client)
    response = _capture(client, PNG_1X1, data={"device_reported_face": "true"})

    body = response.json()
    assert response.status_code == 200
    assert body["received"] is True
    assert body["face_detection_performed"] is False
    assert body["face_detected"] is None
    assert body["device_reported_face"] is True
    assert "not a detection result" in body["message"]


def test_raw_device_face_header_is_not_treated_as_detection(client):
    register_device(client)
    response = client.post(
        "/api/v1/camera/capture",
        headers={
            **device_headers(),
            "Content-Type": "image/png",
            "X-Device-Reported-Face": "true",
        },
        content=PNG_1X1,
    )

    body = response.json()
    assert response.status_code == 200
    assert body["image_format"] == "PNG"
    assert body["face_detected"] is None
    assert body["device_reported_face"] is True


def test_disabled_detector_ignores_a_device_claim():
    image = ValidatedImage(content=PNG_1X1, image_format="PNG", byte_count=len(PNG_1X1))
    outcome = DisabledFaceDetector().evaluate(image, DeviceDetectionClaim(face_reported=True))

    assert outcome.performed is False
    assert outcome.face_detected is None
    assert outcome.source is None


def test_unimplemented_detectors_do_not_report_a_face():
    import pytest

    from app.core.errors import DetectionNotAvailable

    image = ValidatedImage(content=PNG_1X1, image_format="PNG", byte_count=len(PNG_1X1))
    claim = DeviceDetectionClaim(face_reported=True)

    for detector in (UnimplementedServerDetector(), UnimplementedDeviceDetector()):
        with pytest.raises(DetectionNotAvailable):
            detector.evaluate(image, claim)