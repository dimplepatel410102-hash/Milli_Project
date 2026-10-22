"""JSON error responses. Response bodies do not include tracebacks or image bytes."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import MilliError
from app.core.logging import get_logger, safe_error_text

logger = get_logger()


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MilliError, _milli_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(Exception, _unexpected_error)


async def _milli_error(_request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, MilliError) else MilliError("The request could not be processed.")
    return JSONResponse(status_code=error.status_code, content=error.to_body())


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    details = []
    if isinstance(exc, RequestValidationError):
        for item in exc.errors():
            details.append(
                {
                    "loc": [str(part) for part in item.get("loc", ())],
                    "msg": str(item.get("msg", "Invalid value")),
                    "type": str(item.get("type", "value_error")),
                }
            )
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_request",
            "message": "Request validation failed.",
            "details": details,
        },
    )


async def _http_exception(_request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    codes = {
        404: "not_found",
        405: "method_not_allowed",
        413: "payload_too_large",
    }
    detail = exc.detail if isinstance(exc, StarletteHTTPException) else "The request could not be processed."
    if not isinstance(detail, str):
        detail = "The request could not be processed."
    return JSONResponse(
        status_code=status,
        content={
            "error": codes.get(status, "invalid_request" if status < 500 else "processing_failed"),
            "message": detail,
        },
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error path=%s error=%s",
        request.url.path,
        safe_error_text(exc),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "processing_failed",
            "message": "The request could not be processed.",
        },
    )
