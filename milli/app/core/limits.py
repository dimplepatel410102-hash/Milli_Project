"""Reject oversized HTTP bodies before the route reads them into memory."""

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    """Return 413 when Content-Length is above the configured body limit.

    Clients that omit Content-Length are still limited when the image bytes
    are read. A reverse proxy should enforce the same limit in production.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        raw_length = headers.get("content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                await _send_json(
                    send,
                    400,
                    {
                        "error": "invalid_request",
                        "message": "Content-Length is invalid.",
                    },
                )
                return
            if length < 0 or length > self.max_bytes:
                await _send_json(
                    send,
                    413,
                    {
                        "error": "payload_too_large",
                        "message": "Request body exceeds the configured limit.",
                        "received": False,
                        "face_detection_performed": False,
                    },
                )
                return

        await self.app(scope, receive, send)


async def _send_json(send: Send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    message: Message = {"type": "http.response.body", "body": body}
    await send(message)
