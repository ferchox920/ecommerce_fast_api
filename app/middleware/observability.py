from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.metrics import normalize_path, record_request_metrics


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware to collect latency metrics and emit structured error logs."""

    def __init__(self, app, *, log_4xx: bool = True, log_5xx: bool = True) -> None:
        super().__init__(app)
        self.logger = get_logger("app.requests")
        self.log_4xx = log_4xx
        self.log_5xx = log_5xx

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            record_request_metrics(request, 500, duration)
            self._log_error(
                request,
                status_code=500,
                duration=duration,
                message="Unhandled server error",
                level="error",
            )
            raise

        duration = time.perf_counter() - start
        status_code = response.status_code
        record_request_metrics(request, status_code, duration)

        if status_code >= 500 and self.log_5xx:
            self._log_error(request, status_code, duration, "Server error response", "error")
        elif status_code >= 400 and self.log_4xx:
            self._log_error(request, status_code, duration, "Client error response", "warning")

        return response

    def _log_error(
        self,
        request: Request,
        status_code: int,
        duration: float,
        message: str,
        level: str,
    ) -> None:
        payload: dict[str, Any] = {
            "method": request.method,
            "path": normalize_path(request),
            "status_code": status_code,
            "duration_ms": round(duration * 1000, 3),
            "client_ip": self._client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "request_id": request.headers.get("x-request-id"),
        }
        log_func = getattr(self.logger, level, self.logger.error)
        log_func(message, extra=payload)

    @staticmethod
    def _client_ip(request: Request) -> str | None:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else None
