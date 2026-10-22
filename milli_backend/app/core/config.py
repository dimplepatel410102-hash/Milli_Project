from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pillow format names that the image validator knows how to decode.
SUPPORTED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "BMP", "WEBP", "GIF", "TIFF"})

# Room for multipart boundaries and headers on top of the raw image bytes.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables prefixed with MILLI_ and from .env."""

    model_config = SettingsConfigDict(
        env_prefix="MILLI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    enable_docs: bool = True

    # Comma-separated "device_id:sha256_hex_of_api_key" entries.
    # Generate entries with: python -m app.tools.device_key new <device_id>
    device_credentials: str = ""
    require_registration: bool = False

    max_image_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_image_pixels: int = Field(default=25_000_000, ge=1, le=100_000_000)
    allowed_image_formats: str = "JPEG,PNG,BMP,WEBP"

    face_detector: Literal["none", "opencv_haar", "opencv_yunet"] = "none"
    face_min_confidence: float = Field(default=0.6, gt=0, lt=1)
    # Recognition always detects with YuNet, whatever face_detector says.
    face_recognition: bool = False
    face_match_threshold: float = Field(default=0.363, gt=0, lt=1)
    face_model_dir: Path = Path("models")
    face_db_path: Path = Path("data/faces.json")

    store_images: bool = False
    storage_dir: Path = Path("data/captures")
    storage_max_age_seconds: int = Field(default=3600, ge=0)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("allowed_image_formats")
    @classmethod
    def _check_formats(cls, value: str) -> str:
        formats = [item.strip().upper() for item in value.split(",") if item.strip()]
        if not formats:
            raise ValueError("at least one image format must be allowed")
        unknown = sorted(set(formats) - SUPPORTED_IMAGE_FORMATS)
        if unknown:
            raise ValueError(
                f"unsupported image format(s) {unknown}; choose from {sorted(SUPPORTED_IMAGE_FORMATS)}"
            )
        return ",".join(dict.fromkeys(formats))

    @property
    def allowed_formats(self) -> tuple[str, ...]:
        return tuple(self.allowed_image_formats.split(","))

    @property
    def max_request_bytes(self) -> int:
        return self.max_image_bytes + MULTIPART_OVERHEAD_BYTES


@lru_cache
def get_settings() -> Settings:
    return Settings()
