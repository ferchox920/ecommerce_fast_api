from __future__ import annotations

from typing import Callable

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger


class PayloadLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose payload exceeds the configured limit."""

    def __init__(self, app, max_bytes: int | None = None) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes or settings.MAX_REQUEST_SIZE_BYTES
        self.logger = get_logger("app.request_limit")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return self._reject(request, int(content_length))
            except ValueError:
                pass

        body = await request.body()
        if len(body) > self.max_bytes:
            return self._reject(request, len(body))

        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        request._body = body  # type: ignore[attr-defined]
        request._stream_consumed = False  # type: ignore[attr-defined]
        request._receive = receive  # type: ignore[attr-defined]

        return await call_next(request)

    def _reject(self, request: Request, size: int) -> JSONResponse:
        self.logger.warning(
            "Rejected request exceeding payload limit",
            extra={
                "method": request.method,
                "path": request.url.path,
                "content_length": size,
                "client_ip": self._client_ip(request),
            },
        )
        return JSONResponse(
            {"detail": "Request payload too large."},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    @staticmethod
    def _client_ip(request: Request) -> str | None:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else None
