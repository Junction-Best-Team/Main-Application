"""Bound message JSON before FastAPI buffers/parses base64 attachments, including chunked uploads."""

import json

MAX_MESSAGE_BODY = 6 * 1024 * 1024


class MessageBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope.get("path", "").startswith("/api/conversations/")
            or not scope["path"].endswith("/messages")
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_MESSAGE_BODY:
                error = json.dumps(
                    {
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "Message is too large. Use up to 3 files, 2 MB each and 4 MB total.",
                        }
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"no-store"),
                            (b"x-content-type-options", b"nosniff"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": error})
                return
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            nonlocal body
            if body is not None:
                data, body = bytes(body), None
                return {"type": "http.request", "body": data, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
