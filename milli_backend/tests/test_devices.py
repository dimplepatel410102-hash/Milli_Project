import pytest

from tests.conftest import AUTH, DEVICE_ID, DEVICE_KEY, OTHER_DEVICE_KEY, REGISTER_URL, error_code

PAYLOAD = {"firmware_version": "0.1.0", "hardware_model": "ESP32-S3-N16R8"}


def test_register_authorized_device(client):
    response = client.post(REGISTER_URL, json=PAYLOAD, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == DEVICE_ID
    assert body["status"] == "registered"
    assert body["registration_persisted"] is False
    assert body["server_face_detector"] == "none"
    assert body["upload"]["endpoint"] == "/api/v1/camera/capture"
    assert body["upload"]["multipart_field"] == "image"
    assert "JPEG" in body["upload"]["allowed_image_formats"]


def test_reregistration_reports_updated(client):
    client.post(REGISTER_URL, json=PAYLOAD, headers=AUTH)
    response = client.post(REGISTER_URL, json={**PAYLOAD, "firmware_version": "0.2.0"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == "updated"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Device-ID": DEVICE_ID},
        {"X-Device-Key": DEVICE_KEY},
    ],
    ids=["no-headers", "id-only", "key-only"],
)
def test_missing_credentials_rejected(client, headers):
    response = client.post(REGISTER_URL, json=PAYLOAD, headers=headers)

    assert response.status_code == 401
    assert error_code(response) == "unauthorized_device"
    assert response.headers["WWW-Authenticate"] == "ApiKey"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Device-ID": DEVICE_ID, "X-Device-Key": "wrong-key"},
        {"X-Device-ID": "unknown-cam", "X-Device-Key": DEVICE_KEY},
        {"X-Device-ID": DEVICE_ID, "X-Device-Key": OTHER_DEVICE_KEY},
        {"X-Device-ID": "../etc/passwd", "X-Device-Key": DEVICE_KEY},
        {"X-Device-ID": DEVICE_ID, "X-Device-Key": "x" * 1000},
    ],
    ids=["wrong-key", "unknown-device", "other-devices-key", "malformed-id", "oversized-key"],
)
def test_invalid_credentials_rejected_with_identical_message(client, headers):
    response = client.post(REGISTER_URL, json=PAYLOAD, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized_device",
        "message": "Invalid device credentials.",
    }


def test_no_devices_configured_rejects_everyone(make_client):
    client = make_client(device_credentials="")
    assert client.post(REGISTER_URL, json=PAYLOAD, headers=AUTH).status_code == 401


def test_auth_checked_before_body_validation(client):
    response = client.post(REGISTER_URL, json={}, headers={"X-Device-ID": DEVICE_ID, "X-Device-Key": "bad"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"firmware_version": ""},
        {"firmware_version": "1.0; rm -rf /"},
        {"firmware_version": "1.0", "unexpected": True},
        {"firmware_version": "1.0", "hardware_model": "x" * 200},
    ],
    ids=["missing-firmware", "empty-firmware", "bad-chars", "extra-field", "too-long"],
)
def test_invalid_registration_body(client, payload):
    response = client.post(REGISTER_URL, json=payload, headers=AUTH)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]


def test_malformed_json_body(client):
    response = client.post(
        REGISTER_URL, content=b"{not json", headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
