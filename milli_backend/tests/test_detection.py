import pytest
from PIL import Image

from app.services.detection import DetectorUnavailable, DisabledFaceDetector, build_face_detector
from tests.conftest import AUTH, CAPTURE_URL, image_bytes


def test_disabled_detector_does_not_claim_detection():
    outcome = DisabledFaceDetector().detect(Image.new("RGB", (10, 10)))
    assert outcome.performed is False
    assert outcome.faces == ()


def test_unknown_detector_name():
    with pytest.raises(DetectorUnavailable):
        build_face_detector("magic")


def test_opencv_haar_detector_runs_end_to_end(make_client):
    pytest.importorskip("cv2")
    client = make_client(face_detector="opencv_haar")

    body = client.post(CAPTURE_URL, content=image_bytes(size=(320, 240)), headers=AUTH).json()

    detection = body["server_detection"]
    assert body["face_detection_performed"] is True
    assert detection["performed"] is True
    assert detection["detector"] == "opencv_haar"
    # A flat synthetic image contains no face.
    assert detection["face_count"] == 0
    assert detection["face_detected"] is False
