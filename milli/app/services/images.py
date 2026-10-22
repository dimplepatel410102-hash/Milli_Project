"""Validate uploaded bytes as an image. This module does not open a camera."""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from app.core.errors import MissingImage, PayloadTooLarge, UnsupportedImage

# Camera and interchange formats Phase 1 can validate. The camera is not
# required to use any one of these; unknown bytes are rejected.
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "BMP", "GIF", "WEBP", "TIFF"})
FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "BMP": ".bmp",
    "GIF": ".gif",
    "WEBP": ".webp",
    "TIFF": ".tif",
}

# Bound decoded pixel count so a small compressed file cannot expand without limit.
Image.MAX_IMAGE_PIXELS = 8_000_000

UNSUPPORTED_MESSAGE = (
    "Uploaded content is not a supported image. "
    "Supported formats are JPEG, PNG, BMP, GIF, WEBP, and TIFF."
)


@dataclass(frozen=True)
class ValidatedImage:
    content: bytes
    image_format: str
    byte_count: int

    @property
    def extension(self) -> str:
        return FORMAT_EXTENSIONS[self.image_format]


def validate_image(data: bytes) -> ValidatedImage:
    """Decode the bytes enough to prove they are an allowed image.

    The declared HTTP content type and the filename are ignored.
    """
    if not data:
        raise MissingImage(
            "Image data is missing.",
            received=False,
            face_detection_performed=False,
        )
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            if image_format not in ALLOWED_IMAGE_FORMATS:
                raise UnsupportedImage(
                    UNSUPPORTED_MESSAGE,
                    received=False,
                    face_detection_performed=False,
                )
            image.load()
    except (MissingImage, UnsupportedImage, PayloadTooLarge):
        raise
    except DecompressionBombError as exc:
        raise PayloadTooLarge(
            "Image exceeds the configured size limit.",
            received=False,
            face_detection_performed=False,
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise UnsupportedImage(
            UNSUPPORTED_MESSAGE,
            received=False,
            face_detection_performed=False,
        ) from exc
    return ValidatedImage(content=data, image_format=image_format, byte_count=len(data))
