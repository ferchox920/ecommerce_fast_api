from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach strict security headers to every HTTP response."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Strict-Transport-Security", settings.STRICT_TRANSPORT_SECURITY)
        response.headers.setdefault("Content-Security-Policy", settings.CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Frame-Options", settings.X_FRAME_OPTIONS)
        response.headers.setdefault("X-Content-Type-Options", settings.X_CONTENT_TYPE_OPTIONS)
        response.headers.setdefault("Referrer-Policy", settings.REFERRER_POLICY)
        return response
