"""ASGI middleware that caps request body size for every route.

Requests that declare a too-large Content-Length are rejected before any body
is read. Chunked uploads without Content-Length are counted while streaming.
"""

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body


class RequestBodyTooLarge(HTTPException):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=f"Request body exceeds the {max_bytes} byte limit.")


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared == -1:
            await JSONResponse(
                error_body("invalid_request", "Invalid Content-Length header."), status_code=400
            )(scope, receive, send)
            return
        if declared is not None and declared > self.max_bytes:
            await JSONResponse(
                error_body("payload_too_large", RequestBodyTooLarge(self.max_bytes).detail),
                status_code=413,
            )(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge(self.max_bytes)
            return message

        await self.app(scope, limited_receive, send)


def _content_length(scope: Scope) -> int | None:
    """Return the declared Content-Length, None if absent, or -1 if malformed."""
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                length = int(value)
            except ValueError:
                return -1
            return length if length >= 0 else -1
    return None
