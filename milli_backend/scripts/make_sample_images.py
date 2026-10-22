"""Generate synthetic test images for exercising the API without camera hardware.

    .\\.venv\\Scripts\\python.exe scripts\\make_sample_images.py

The images are plain gradients and contain no faces, so a server-side
detector should report zero faces for them.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "samples"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    image = Image.new("RGB", (320, 240))
    draw = ImageDraw.Draw(image)
    for x in range(320):
        draw.line([(x, 0), (x, 239)], fill=(x * 255 // 319, 96, 255 - x * 255 // 319))
    draw.text((10, 10), "Milli test image", fill=(255, 255, 255))

    image.save(OUT / "sample.jpg", "JPEG", quality=85)
    image.save(OUT / "sample.png", "PNG")
    image.save(OUT / "sample.bmp", "BMP")
    image.save(OUT / "sample.gif", "GIF")  # rejected unless GIF is allowed
    (OUT / "not_an_image.txt").write_text("this is not an image\n", encoding="utf-8")
    jpeg = (OUT / "sample.jpg").read_bytes()
    (OUT / "truncated.jpg").write_bytes(jpeg[: len(jpeg) // 2])

    for path in sorted(OUT.iterdir()):
        print(f"{path.name:20} {path.stat().st_size:>8} bytes")


if __name__ == "__main__":
    main()
