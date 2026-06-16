"""Prometheus metrics for admin-service."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

REQUEST_COUNT = Counter(
    "admin_api_requests_total",
    "Total admin API HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "admin_api_request_duration_seconds",
    "Admin API request latency",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def metrics_response() -> Response:
    """Return Prometheus scrape payload."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def prometheus_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Record request count and latency."""
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    if len(path) > 80:
        path = path[:77] + "..."
    REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    return response
