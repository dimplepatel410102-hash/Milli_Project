"""Device registration and credential checks."""

import logging

import pytest
from pydantic import ValidationError

from app.core.credentials import (
    CredentialConfigError,
    key_is_usable,
    parse_device_credentials,
)
from app.main import create_app
from tests.conftest import API_KEY, DEVICE_ID, device_headers, make_settings, register_device


def test_register_configured_device(client):
    response = register_device(client)

    assert response.status_code == 201
    body = response.json()
    assert body["device_id"] == DEVICE_ID
    assert body["registered"] is True
    assert body["registered_at"]
    assert body["message"] == "Device registered."
    assert API_KEY not in response.text


def test_register_again_refreshes_the_same_device(client):
    first = register_device(client)
    second = register_device(client)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["registered_at"] == first.json()["registered_at"]
    assert second.json()["message"] == "Device registration refreshed."


def test_register_rejects_wrong_key_without_logging_it(client, caplog):
    wrong_key = "wrong-key-0123456789"
    with caplog.at_level(logging.INFO, logger="milli"):
        response = register_device(client, api_key=wrong_key)

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert response.json()["message"] == "Device credentials were rejected."
    assert wrong_key not in response.text
    assert wrong_key not in caplog.text
    assert "key_mismatch" in caplog.text


def test_register_rejects_missing_key(client):
    response = client.post(
        "/api/v1/devices/register",
        json={"device_id": DEVICE_ID},
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Device credentials are required."


def test_register_rejects_unknown_device(client, caplog):
    with caplog.at_level(logging.INFO, logger="milli"):
        response = register_device(client, device_id="other-device")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert "unknown_device" in caplog.text


def test_register_rejects_placeholder_key():
    app = create_app(
        make_settings(device_credentials=f"{DEVICE_ID}:replace-with-a-long-random-key")
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = register_device(client, api_key="replace-with-a-long-random-key")

    assert response.status_code == 401
    assert "replace-with-a-long-random-key" not in response.text


def test_register_rejects_short_configured_key(caplog):
    from fastapi.testclient import TestClient

    app = create_app(make_settings(device_credentials=f"{DEVICE_ID}:zz"))
    with TestClient(app) as client:
        with caplog.at_level(logging.INFO, logger="milli"):
            response = register_device(client, api_key="zz")

    assert response.status_code == 401
    assert "zz" not in response.text
    assert "unusable_configured_key" in caplog.text


def test_register_rejects_malformed_device_id(client):
    response = client.post(
        "/api/v1/devices/register",
        headers={"X-Device-Key": API_KEY},
        json={"device_id": "bad id"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_register_rejects_extra_fields_without_echoing_them(client):
    response = client.post(
        "/api/v1/devices/register",
        headers={"X-Device-Key": API_KEY},
        json={"device_id": DEVICE_ID, "api_key": "do-not-echo-this-secret"},
    )

    assert response.status_code == 422
    assert "do-not-echo-this-secret" not in response.text


def test_capture_headers_are_not_enough_without_registration(client):
    response = client.post(
        "/api/v1/camera/capture",
        headers=device_headers(),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "device_not_registered"
    assert body["received"] is False
    assert body["face_detection_performed"] is False


def test_parse_credentials_and_reject_invalid_config():
    parsed = parse_device_credentials("lobby-1:abcdefghijklmnopqrstuvwxyz,door-2:another-long-key-value")
    assert parsed == {
        "lobby-1": "abcdefghijklmnopqrstuvwxyz",
        "door-2": "another-long-key-value",
    }
    assert key_is_usable("replace-with-a-long-random-key") is False
    assert key_is_usable("short") is False
    assert key_is_usable("a-real-local-test-key") is True

    with pytest.raises(CredentialConfigError):
        parse_device_credentials("missing-separator")
    with pytest.raises(CredentialConfigError):
        parse_device_credentials("lobby-1:abc,lobby-1:defghijklmnopqrs")
    with pytest.raises(ValidationError):
        make_settings(device_credentials="not a credential")
    with pytest.raises(ValidationError):
        make_settings(face_detection_mode="magic")
