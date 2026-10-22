import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.core.security import hash_api_key
from app.factory import create_app

# Test-only credentials; they exist nowhere else.
DEVICE_ID = "test-cam-01"
DEVICE_KEY = "test-only-key-for-test-cam-01-0000000000"
OTHER_DEVICE_ID = "test-cam-02"
OTHER_DEVICE_KEY = "test-only-key-for-test-cam-02-0000000000"

AUTH = {"X-Device-ID": DEVICE_ID, "X-Device-Key": DEVICE_KEY}

CAPTURE_URL = "/api/v1/camera/capture"
REGISTER_URL = "/api/v1/devices/register"


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MILLI_"):
            monkeypatch.delenv(name)


def make_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "device_credentials": (
            f"{DEVICE_ID}:{hash_api_key(DEVICE_KEY)},{OTHER_DEVICE_ID}:{hash_api_key(OTHER_DEVICE_KEY)}"
        ),
        "face_detector": "none",
        "store_images": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def make_client():
    def _make(detector=None, **overrides) -> TestClient:
        return TestClient(create_app(make_settings(**overrides), face_detector=detector))

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buffer, fmt)
    return buffer.getvalue()


def error_code(response) -> str:
    return response.json()["error"]["code"]
