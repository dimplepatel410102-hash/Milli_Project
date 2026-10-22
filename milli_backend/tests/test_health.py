from app import __version__


def test_health_returns_status_and_version(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["service"] == "milli-backend"
    assert "server_time" in body


def test_health_needs_no_credentials(client):
    assert client.get("/health", headers={"X-Device-Key": "wrong"}).status_code == 200


def test_swagger_docs_and_openapi_available(client):
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()

    spec = client.get("/openapi.json").json()
    assert "/health" in spec["paths"]
    assert "/api/v1/devices/register" in spec["paths"]
    capture = spec["paths"]["/api/v1/camera/capture"]["post"]
    assert "multipart/form-data" in capture["requestBody"]["content"]
    assert "application/octet-stream" in capture["requestBody"]["content"]
    assert {"DeviceId", "DeviceKey"} <= set(spec["components"]["securitySchemes"])


def test_docs_can_be_disabled(make_client):
    client = make_client(enable_docs=False)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/health").status_code == 200


def test_features_lists_placeholders_honestly(client):
    features = {f["name"]: f["status"] for f in client.get("/api/v1/features").json()["features"]}

    assert features["image_capture"] == "available"
    for optional in ("server_face_detection", "face_recognition", "employee_enrollment"):
        assert features[optional] == "optional"
    for planned in ("attendance", "liveness_check", "consent_management", "visitor_handling",
                    "appointment_check_in"):
        assert features[planned] == "placeholder"


def test_unknown_route_uses_error_shape(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method_uses_error_shape(client):
    response = client.get("/api/v1/camera/capture")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
