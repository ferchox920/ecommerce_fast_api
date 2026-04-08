from __future__ import annotations

import time
from typing import Any

from app.core.config import settings

try:  # pragma: no cover - optional dependency fallback
    from prometheus_client import Counter, Histogram, generate_latest
    from prometheus_client.exposition import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover - optional dependency fallback
    Counter = Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"  # type: ignore[assignment]


class _NoOpMetric:
    def labels(self, *args: Any, **kwargs: Any) -> "_NoOpMetric":
        return self

    def observe(self, *_: Any, **__: Any) -> None:
        return None

    def inc(self, *_: Any, **__: Any) -> None:
        return None


def _metric_or_noop(metric_factory: Any) -> Any:
    if not settings.METRICS_ENABLED or metric_factory is None:
        return _NoOpMetric()
    return metric_factory


REQUEST_LATENCY = _metric_or_noop(
    None
    if Histogram is None
    else Histogram(
        f"{settings.METRICS_NAMESPACE}_http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path", "status_code"],
        buckets=settings.METRICS_LATENCY_BUCKETS,
    )
)

REQUEST_COUNT = _metric_or_noop(
    None
    if Counter is None
    else Counter(
        f"{settings.METRICS_NAMESPACE}_http_requests_total",
        "Total HTTP requests processed.",
        ["method", "path", "status_code"],
    )
)

REQUEST_ERRORS = _metric_or_noop(
    None
    if Counter is None
    else Counter(
        f"{settings.METRICS_NAMESPACE}_http_errors_total",
        "Total HTTP requests resulting in 4xx/5xx.",
        ["method", "path", "status_code"],
    )
)

LOGIN_ATTEMPTS = _metric_or_noop(
    None
    if Counter is None
    else Counter(
        f"{settings.METRICS_NAMESPACE}_auth_login_attempts_total",
        "Authentication attempts partitioned by outcome.",
        ["outcome"],
    )
)

EXPOSURE_REQUESTS = _metric_or_noop(
    None
    if Counter is None
    else Counter(
        f"{settings.METRICS_NAMESPACE}_exposure_requests_total",
        "Total exposure requests partitioned by context and cache outcome.",
        ["context", "cache"],
    )
)

EXPOSURE_ITEMS_SERVED = _metric_or_noop(
    None
    if Counter is None
    else Counter(
        f"{settings.METRICS_NAMESPACE}_exposure_items_served_total",
        "Total number of items served by exposure context.",
        ["context"],
    )
)

EXPOSURE_LATENCY = _metric_or_noop(
    None
    if Histogram is None
    else Histogram(
        f"{settings.METRICS_NAMESPACE}_exposure_duration_seconds",
        "Exposure generation/lookup latency in seconds.",
        ["context", "cache"],
        buckets=settings.METRICS_LATENCY_BUCKETS,
    )
)


def normalize_path(request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return request.url.path


def record_request_metrics(request, status_code: int, elapsed: float) -> None:
    method = request.method
    path = normalize_path(request)
    labels = (method, path, str(status_code))
    REQUEST_COUNT.labels(*labels).inc()
    REQUEST_LATENCY.labels(*labels).observe(elapsed)
    if status_code >= 400:
        REQUEST_ERRORS.labels(*labels).inc()


def record_login_attempt(outcome: str) -> None:
    LOGIN_ATTEMPTS.labels(outcome=outcome).inc()


def record_exposure_metrics(*, context: str, cache_hit: bool, items_served: int, elapsed: float) -> None:
    cache_label = "hit" if cache_hit else "miss"
    EXPOSURE_REQUESTS.labels(context=context, cache=cache_label).inc()
    EXPOSURE_ITEMS_SERVED.labels(context=context).inc(items_served)
    EXPOSURE_LATENCY.labels(context=context, cache=cache_label).observe(elapsed)


def export_metrics() -> tuple[bytes, str]:
    if not settings.METRICS_ENABLED or generate_latest is None:
        return b"", "text/plain; charset=utf-8"
    return generate_latest(), CONTENT_TYPE_LATEST  # type: ignore[return-value]
