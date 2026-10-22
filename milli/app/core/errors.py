"""Application errors mapped to HTTP responses by the API layer."""


class MilliError(Exception):
    """Safe error that can be returned to a client."""

    status_code = 400
    code = "invalid_request"

    def __init__(
        self,
        message: str,
        *,
        received: bool | None = None,
        face_detection_performed: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.received = received
        self.face_detection_performed = face_detection_performed

    def to_body(self) -> dict:
        body: dict = {"error": self.code, "message": self.message}
        if self.received is not None:
            body["received"] = self.received
        if self.face_detection_performed is not None:
            body["face_detection_performed"] = self.face_detection_performed
        return body


class InvalidRequest(MilliError):
    status_code = 400
    code = "invalid_request"


class UnauthorizedDevice(MilliError):
    status_code = 401
    code = "unauthorized"


class DeviceNotRegistered(MilliError):
    status_code = 403
    code = "device_not_registered"


class MissingImage(MilliError):
    status_code = 400
    code = "missing_image"


class PayloadTooLarge(MilliError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedImage(MilliError):
    status_code = 415
    code = "unsupported_image"


class ProcessingFailed(MilliError):
    status_code = 500
    code = "processing_failed"


class DetectionNotAvailable(MilliError):
    status_code = 501
    code = "detection_not_available"
