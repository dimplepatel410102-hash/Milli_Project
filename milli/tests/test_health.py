"""Health endpoint and OpenAPI documentation."""

from fastapi.testclient import TestClient

from tests.conftest import make_settings
from app.main import create_app


def test_health_reports_status_and_version(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Milli Test"
    assert body["version"] == "0.1.0-test"
    assert body["environment"] == "test"
    assert body["face_detection_mode"] == "disabled"


def test_health_does_not_require_credentials(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert "test-api-key" not in response.text


def test_health_works_when_no_devices_are_configured():
    app = create_app(make_settings(device_credentials=""))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_and_swagger_are_available(client):
    docs = client.get("/docs")
    schema = client.get("/openapi.json")

    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/devices/register" in paths
    assert "/api/v1/camera/capture" in paths
    assert "DeviceApiKey" in schema.text


def test_unknown_path_returns_json(client):
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "Traceback" not in response.text
