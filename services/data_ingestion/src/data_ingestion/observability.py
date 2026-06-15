"""Prometheus metrics and OpenTelemetry spans for data ingestion."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypeVar

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Gauge, Histogram

_OTEL_INITIALIZED = False

T = TypeVar("T")


def setup_otel(service_name: str = "data-ingestion") -> None:
    """Configure OpenTelemetry tracing (OTLP when endpoint is set)."""
    global _OTEL_INITIALIZED  # noqa: PLW0603
    if _OTEL_INITIALIZED:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _OTEL_INITIALIZED = True


setup_otel()
tracer = trace.get_tracer("data_ingestion")

ingestion_records_total = Counter(
    "ingestion_records_total",
    "Records persisted by ingestion writers",
    labelnames=("adapter", "market"),
)

ingestion_errors_total = Counter(
    "ingestion_errors_total",
    "Ingestion failures",
    labelnames=("adapter", "reason"),
)

ingestion_duration_seconds = Histogram(
    "ingestion_duration_seconds",
    "End-to-end duration of adapter fetch or writer flush",
    labelnames=("adapter", "market"),
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

ingestion_last_success_timestamp = Gauge(
    "ingestion_last_success_timestamp",
    "Unix timestamp of the last successful market ingest",
    labelnames=("market",),
)


def record_success(market: str) -> None:
    """Stamp last-success gauge for a market."""
    ingestion_last_success_timestamp.labels(market=market).set(
        datetime.now(tz=UTC).timestamp(),
    )


def record_error(adapter: str, reason: str) -> None:
    """Increment the error counter."""
    ingestion_errors_total.labels(adapter=adapter, reason=reason).inc()


def record_written(adapter: str, market: str, count: int) -> None:
    """Increment records counter when count > 0."""
    if count > 0:
        ingestion_records_total.labels(adapter=adapter, market=market).inc(count)


@asynccontextmanager
async def observe_duration(
    adapter: str,
    market: str = "all",
) -> AsyncIterator[None]:
    """Histogram wrapper for timed ingestion stages."""
    start = time.perf_counter()
    try:
        yield
    finally:
        ingestion_duration_seconds.labels(adapter=adapter, market=market).observe(
            time.perf_counter() - start,
        )


@asynccontextmanager
async def span(name: str, **attributes: str | int | float) -> AsyncIterator[trace.Span]:
    """OpenTelemetry span with optional attributes."""
    with tracer.start_as_current_span(name) as otel_span:
        for key, value in attributes.items():
            otel_span.set_attribute(key, value)
        yield otel_span


async def traced_fetch(  # noqa: UP047 — TypeVar T declared at module level; type param syntax not compatible with Callable generic here
    adapter: str,
    market: str,
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    """Run an adapter fetch inside span + duration metrics."""
    async with observe_duration(adapter, market):  # noqa: SIM117 — async with nesting required; combinable only in 3.10+ and contextmanager types must match
        async with span("adapter.fetch", adapter=adapter, market=market):
            return await coro_factory()
