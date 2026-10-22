"""Read an uploaded image without trusting its filename or content type."""

from fastapi import Request

from app.core.errors import InvalidRequest, MissingImage, PayloadTooLarge
from app.core.logging import get_logger, safe_error_text

logger = get_logger()

_TRUE = {"true", "1"}
_FALSE = {"false", "0"}
CAPTURE_REJECTED = {"received": False, "face_detection_performed": False}


def parse_optional_bool(value: object, field_name: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "":
            return None
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    raise InvalidRequest(
        f"{field_name} must be true or false.",
        **CAPTURE_REJECTED,
    )


async def extract_image(request: Request, max_image_bytes: int) -> tuple[bytes, bool | None]:
    """Return image bytes and an optional unverified device face report."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type == "multipart/form-data":
        return await _read_multipart(request, max_image_bytes)
    if media_type == "application/octet-stream" or media_type.startswith("image/"):
        reported = parse_optional_bool(
            request.headers.get("x-device-reported-face"),
            "X-Device-Reported-Face",
        )
        data = await _read_limited(request.stream(), max_image_bytes)
        return data, reported
    raise InvalidRequest(
        "Send the image as multipart/form-data in a file field named 'image', "
        "or as a raw body with Content-Type application/octet-stream or image/*.",
        **CAPTURE_REJECTED,
    )


async def _read_multipart(request: Request, max_image_bytes: int) -> tuple[bytes, bool | None]:
    try:
        form = await request.form()
    except Exception as exc:
        logger.warning("Multipart body rejected error=%s status=rejected", safe_error_text(exc))
        raise InvalidRequest(
            "The multipart body could not be read. Send one file field named 'image'.",
            **CAPTURE_REJECTED,
        ) from exc
    try:
        uploads = [item for item in form.getlist("image") if hasattr(item, "read")]
        reported = parse_optional_bool(form.get("device_reported_face"), "device_reported_face")
        if len(uploads) == 0:
            raise MissingImage(
                "Image data is missing. Send a multipart file field named 'image'.",
                **CAPTURE_REJECTED,
            )
        if len(uploads) > 1:
            raise InvalidRequest("Send exactly one image.", **CAPTURE_REJECTED)
        data = await _read_limited(uploads[0], max_image_bytes)
        return data, reported
    finally:
        await form.close()


async def _read_limited(source, limit: int) -> bytes:
    """Read an upload file or an async byte stream, stopping at ``limit``."""
    buffer = bytearray()
    read = source.read if hasattr(source, "read") else None
    if read is not None:
        while True:
            chunk = await read(65536)
            if not chunk:
                break
            _append_limited(buffer, chunk, limit)
        return bytes(buffer)

    async for chunk in source:
        _append_limited(buffer, chunk, limit)
    return bytes(buffer)


def _append_limited(buffer: bytearray, chunk: bytes, limit: int) -> None:
    if len(buffer) + len(chunk) > limit:
        raise PayloadTooLarge(
            "Image exceeds the configured size limit.",
            **CAPTURE_REJECTED,
        )
    buffer.extend(chunk)
