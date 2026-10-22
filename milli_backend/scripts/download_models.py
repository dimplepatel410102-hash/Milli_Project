"""Download the OpenCV Zoo face models used by MILLI_FACE_DETECTOR=opencv_yunet and MILLI_FACE_RECOGNITION.

Usage (from milli_backend):  .\\.venv\\Scripts\\python.exe scripts\\download_models.py
Existing files are kept if OpenCV can load them; corrupt or truncated files are replaced.
"""

import sys
import urllib.request
from pathlib import Path

import cv2

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def loads(path: Path) -> bool:
    try:
        if "yunet" in path.name:
            cv2.FaceDetectorYN.create(str(path), "", (320, 240))
        else:
            cv2.FaceRecognizerSF.create(str(path), "")
        return True
    except cv2.error:
        return False


def main() -> int:
    MODEL_DIR.mkdir(exist_ok=True)
    for name, url in MODELS.items():
        target = MODEL_DIR / name
        if target.is_file() and loads(target):
            print(f"ok        {name} ({target.stat().st_size} bytes)")
            continue
        print(f"download  {name} ...")
        partial = target.with_suffix(".part")
        urllib.request.urlretrieve(url, partial)
        if not loads(partial):
            partial.unlink()
            print(f"FAILED    {name}: downloaded file does not load in OpenCV {cv2.__version__}")
            return 1
        partial.replace(target)
        print(f"ok        {name} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
