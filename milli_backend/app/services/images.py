"""Validation of uploaded image bytes.

The format is detected from the bytes themselves; the client's Content-Type
and file name are never trusted.
"""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.errors import InvalidImage, MissingImage, PayloadTooLarge, UnsupportedImage

FILE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "BMP": "bmp", "WEBP": "webp", "GIF": "gif", "TIFF": "tiff"}


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    format: str
    width: int
    height: int
    mode: str
    image: Image.Image

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def extension(self) -> str:
        return FILE_EXTENSIONS.get(self.format, "bin")


class ImageValidator:
    def __init__(self, allowed_formats: tuple[str, ...], max_bytes: int, max_pixels: int) -> None:
        self.allowed_formats = allowed_formats
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels

    def validate(self, data: bytes) -> ValidatedImage:
        if not data:
            raise MissingImage()
        if len(data) > self.max_bytes:
            raise PayloadTooLarge(f"Image exceeds the {self.max_bytes} byte limit.")

        try:
            # Restricting `formats` means only the allowed decoders ever see the bytes.
            image = Image.open(io.BytesIO(data), formats=list(self.allowed_formats))
        except UnidentifiedImageError:
            raise UnsupportedImage(
                f"Uploaded data is not a supported image. Allowed formats: {', '.join(self.allowed_formats)}."
            ) from None
        except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
            raise InvalidImage("The image header could not be read.") from None

        width, height = image.size
        if width <= 0 or height <= 0 or width * height > self.max_pixels:
            raise InvalidImage(
                f"Image dimensions {width}x{height} exceed the {self.max_pixels} pixel limit."
            )

        try:
            image.load()
        except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
            raise InvalidImage("The image data is corrupt or truncated.") from None

        return ValidatedImage(
            data=data,
            format=image.format or "UNKNOWN",
            width=width,
            height=height,
            mode=image.mode,
            image=image,
        )
