"""Application errors and the handlers that turn them into a consistent JSON shape:

    {"error": {"code": "...", "message": "...", "details": [...]}}
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("milli.errors")


class MilliError(Exception):
    status_code = 500
    code = "processing_failed"
    default_message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        self.message = message or self.default_message
        self.headers = headers
        super().__init__(self.message)


class InvalidRequest(MilliError):
    status_code = 400
    code = "invalid_request"
    default_message = "The request is invalid."


class MissingImage(MilliError):
    status_code = 400
    code = "missing_image"
    default_message = "No image data was received."


class UnauthorizedDevice(MilliError):
    status_code = 401
    code = "unauthorized_device"
    default_message = "Invalid device credentials."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "ApiKey"})


class DeviceNotRegistered(MilliError):
    status_code = 403
    code = "device_not_registered"
    default_message = "Device must call /api/v1/devices/register before uploading captures."


class PayloadTooLarge(MilliError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The request body is too large."


class UnsupportedImage(MilliError):
    status_code = 415
    code = "unsupported_image"
    default_message = "The uploaded data is not a supported image."


class InvalidImage(MilliError):
    status_code = 422
    code = "invalid_image"
    default_message = "The image could not be decoded."


class NoFaceDetected(MilliError):
    status_code = 422
    code = "no_face_detected"
    default_message = "No face was detected in the image."


class MultipleFacesDetected(MilliError):
    status_code = 422
    code = "multiple_faces"
    default_message = "More than one face was detected; enrollment needs exactly one."


class NotFound(MilliError):
    status_code = 404
    code = "not_found"
    default_message = "The requested resource does not exist."


class ProcessingFailed(MilliError):
    status_code = 500
    code = "processing_failed"
    default_message = "The image was received but could not be processed."


class RecognitionDisabled(MilliError):
    status_code = 503
    code = "recognition_disabled"
    default_message = "Face recognition is disabled. Set MILLI_FACE_RECOGNITION=true and restart the server."


_HTTP_STATUS_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def error_body(code: str, message: str, details: list | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MilliError)
    async def _milli_error(_: Request, exc: MilliError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return JSONResponse(
            error_body(code, message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Submitted values are deliberately not echoed back.
        details = [
            {"location": [str(part) for part in err.get("loc", ())], "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Request validation failed.", details), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled error path=%s error=%s", request.url.path, type(exc).__name__, exc_info=exc
        )
        return JSONResponse(error_body(ProcessingFailed.code, "Internal server error."), status_code=500)
