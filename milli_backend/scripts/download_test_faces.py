"""Download three public-domain portraits of different people for the real-model recognition test.

Usage (from milli_backend):  .\\.venv\\Scripts\\python.exe scripts\\download_test_faces.py
Images are saved as tests/face_photos/person_{a,b,c}.jpg (max 400 px).
"""

import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image

PHOTOS = {
    # Grace Hopper, U.S. Navy photo (public domain), via OpenCV test data.
    "person_a.jpg": "https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/dnn/grace_hopper_227.png",
    # Eileen Collins, NASA photo (public domain), via scikit-image sample data.
    "person_b.jpg": "https://raw.githubusercontent.com/scikit-image/scikit-image/v0.21.0/skimage/data/astronaut.png",
    # Barack Obama, official White House portrait (public domain), via Wikimedia Commons.
    "person_c.jpg": "https://upload.wikimedia.org/wikipedia/commons/8/8d/President_Barack_Obama.jpg",
}
TARGET_DIR = Path(__file__).resolve().parent.parent / "tests" / "face_photos"


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in PHOTOS.items():
        target = TARGET_DIR / name
        if target.is_file():
            print(f"ok        {name}")
            continue
        request = urllib.request.Request(url, headers={"User-Agent": "milli-backend-tests/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            image = Image.open(io.BytesIO(response.read())).convert("RGB")
        image.thumbnail((400, 400))
        image.save(target, "JPEG", quality=90)
        print(f"saved     {name} {image.width}x{image.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
