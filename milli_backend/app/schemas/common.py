from pydantic import BaseModel


class ErrorDetail(BaseModel):
    location: list[str]
    message: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorInfo


def error_responses(*status_codes: int) -> dict[int, dict]:
    descriptions = {
        400: "Invalid request or missing image data",
        401: "Missing or invalid device credentials",
        403: "Device is not registered",
        404: "Not found",
        413: "Request body or image too large",
        415: "Uploaded data is not a supported image",
        422: "Validation failed or image could not be decoded",
        500: "Processing failed",
        503: "Face recognition is disabled",
    }
    return {
        code: {"model": ErrorResponse, "description": descriptions.get(code, "Error")}
        for code in status_codes
    }
