"""Environment-backed settings. Secrets are read from the environment, not source code."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.credentials import CredentialConfigError, parse_device_credentials

BODY_OVERHEAD_BYTES = 8192
MAX_CONFIGURABLE_IMAGE_BYTES = 8 * 1024 * 1024
DETECTION_MODES = frozenset({"disabled", "server", "device"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class Settings(BaseSettings):
    """Process configuration loaded from the environment and an optional ``.env`` file."""

    model_config = SettingsConfigDict(
        env_prefix="MILLI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Milli Face Detection Backend"
    version: str = "0.1.0"
    env: str = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    max_image_bytes: int = 1_048_576
    store_images: bool = False
    retain_temp_images: bool = False
    temp_dir: str = ""
    device_credentials: str = ""
    face_detection_mode: str = "disabled"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(
                "MILLI_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."
            )
        return level

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("MILLI_PORT must be between 1 and 65535.")
        return value

    @field_validator("max_image_bytes")
    @classmethod
    def validate_max_image_bytes(cls, value: int) -> int:
        if value < 1 or value > MAX_CONFIGURABLE_IMAGE_BYTES:
            raise ValueError(
                "MILLI_MAX_IMAGE_BYTES must be between 1 and 8388608 (8 MiB)."
            )
        return value

    @field_validator("face_detection_mode")
    @classmethod
    def validate_detection_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in DETECTION_MODES:
            raise ValueError(
                "MILLI_FACE_DETECTION_MODE must be 'disabled', 'server', or 'device'. "
                "Only 'disabled' accepts images without running a detector. "
                "'server' and 'device' are reserved and do not produce a face result."
            )
        return mode

    @field_validator("device_credentials")
    @classmethod
    def validate_device_credentials(cls, value: str) -> str:
        try:
            parse_device_credentials(value)
        except CredentialConfigError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @property
    def max_body_bytes(self) -> int:
        """HTTP body ceiling: the image limit plus a small multipart overhead."""
        return self.max_image_bytes + BODY_OVERHEAD_BYTES


@lru_cache
def get_settings() -> Settings:
    return Settings()
