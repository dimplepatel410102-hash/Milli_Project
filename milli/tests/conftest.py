"""Shared test fixtures. Credentials here are fake and exist only inside the test process."""

import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

DEVICE_ID = "test-device"
API_KEY = "test-api-key-0123456789"

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_name": "Milli Test",
        "version": "0.1.0-test",
        "env": "test",
        "log_level": "INFO",
        "host": "127.0.0.1",
        "port": 8000,
        "max_image_bytes": 1_048_576,
        "store_images": False,
        "retain_temp_images": False,
        "temp_dir": "",
        "device_credentials": f"{DEVICE_ID}:{API_KEY}",
        "face_detection_mode": "disabled",
    }
    values.update(overrides)
    return Settings(**values)


def device_headers(device_id: str = DEVICE_ID, api_key: str = API_KEY) -> dict[str, str]:
    return {"X-Device-Id": device_id, "X-Device-Key": api_key}


def register_device(client: TestClient, device_id: str = DEVICE_ID, api_key: str = API_KEY):
    return client.post(
        "/api/v1/devices/register",
        headers={"X-Device-Key": api_key},
        json={"device_id": device_id},
    )


@pytest.fixture(autouse=True)
def clear_milli_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MILLI_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings():
    return make_settings()


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
