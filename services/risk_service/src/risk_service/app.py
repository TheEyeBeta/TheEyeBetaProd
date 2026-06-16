"""Risk-service application — gRPC servicer and HTTP bridge."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from concurrent import futures

import grpc
import structlog
import uvicorn
from fastapi import FastAPI, Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from risk_service.metrics import (
    compute_metrics_from_context,
    insert_risk_metrics,
    load_portfolio_context,
)
from risk_service.models import OrderProposal, RiskOutcome, RiskValidationResult
from risk_service.validator import OrderRiskValidator
from zinc_proto import risk_pb2, risk_pb2_grpc

log = structlog.get_logger()

_GRPC_HOST = os.environ.get("RISK_SERVICE_GRPC_HOST", "127.0.0.1")
_GRPC_PORT = int(os.environ.get("RISK_SERVICE_GRPC_PORT", "7060"))
_HTTP_HOST = os.environ.get("RISK_SERVICE_HTTP_HOST", "127.0.0.1")
_HTTP_PORT = int(os.environ.get("RISK_SERVICE_HTTP_PORT", "8007"))


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


class ValidateOrderBody(BaseModel):
    """HTTP bridge body for pre-trade validation."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    instrument_id: int
    side: str
    qty: float
    limit_price: float = 100.0
    order_intent: str = "BUY"
    sector: str = "unknown"
    cluster: str = "default"
    market: str = ""


def build_validator() -> OrderRiskValidator:
    """Return the default six-check validator."""
    return OrderRiskValidator()


async def validate_order_request(
    validator: OrderRiskValidator,
    request: risk_pb2.RiskCheckRequest,
) -> RiskValidationResult:
    """Run validation and persist a ``risk_metrics`` row."""
    dsn = _db_url()
    ctx = await load_portfolio_context(dsn, request.portfolio_id)
    order = OrderProposal(
        instrument_id=int(request.instrument_id),
        side=request.side,
        qty=float(request.qty),
        price=float(request.limit_price or 100.0),
        sector=request.sector or "unknown",
        cluster=request.cluster or "default",
        order_intent=request.order_intent or request.side.upper(),
    )
    result = validator.validate(ctx, order)
    metrics = compute_metrics_from_context(ctx)
    metrics.raw["validation"] = {
        "outcome": result.outcome.name,
        "failed_checks": result.failed_checks,
        "order": {
            "instrument_id": order.instrument_id,
            "side": order.side,
            "qty": order.qty,
        },
    }
    metrics.raw.update({f"check_{k}": v for k, v in result.metrics.items()})
    await insert_risk_metrics(dsn, metrics)
    return result


async def compute_portfolio_metrics_request(
    portfolio_id: str,
) -> risk_pb2.PortfolioMetrics:
    """Recompute and persist portfolio risk metrics."""
    dsn = _db_url()
    ctx = await load_portfolio_context(dsn, portfolio_id)
    metrics = compute_metrics_from_context(ctx)
    await insert_risk_metrics(dsn, metrics)
    return risk_pb2.PortfolioMetrics(
        portfolio_id=portfolio_id,
        var_95=metrics.var_95,
        cvar_95=metrics.cvar_95,
        max_drawdown=metrics.max_drawdown,
        gross_exposure=metrics.gross_exposure,
        net_exposure=metrics.net_exposure,
        beta_spy=metrics.beta_spy,
        concentration_hhi=metrics.concentration_hhi,
    )


def to_proto_decision(result: RiskValidationResult) -> risk_pb2.RiskDecision:
    """Map internal result to protobuf response."""
    outcome_map = {
        RiskOutcome.ALLOW: risk_pb2.ALLOW,
        RiskOutcome.WARN: risk_pb2.WARN,
        RiskOutcome.BLOCK: risk_pb2.BLOCK,
    }
    return risk_pb2.RiskDecision(
        outcome=outcome_map[result.outcome],
        reason=result.reason,
        metrics=result.metrics,
        failed_checks=result.failed_checks,
        approved=result.approved,
    )


class RiskServicer(risk_pb2_grpc.RiskServicer):
    """gRPC servicer for ``ValidateOrder`` and ``ComputePortfolioMetrics``."""

    def __init__(self, validator: OrderRiskValidator) -> None:
        self._validator = validator

    async def ValidateOrder(  # noqa: N802
        self,
        request: risk_pb2.RiskCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> risk_pb2.RiskDecision:
        _ = context
        result = await validate_order_request(self._validator, request)
        return to_proto_decision(result)

    async def ComputePortfolioMetrics(  # noqa: N802
        self,
        request: risk_pb2.PortfolioRequest,
        context: grpc.aio.ServicerContext,
    ) -> risk_pb2.PortfolioMetrics:
        _ = context
        return await compute_portfolio_metrics_request(request.portfolio_id)


def create_http_app(validator: OrderRiskValidator) -> FastAPI:
    """FastAPI app exposing health and HTTP validation bridge."""
    app = FastAPI(title="risk-service", version="0.1.0")
    registry = CollectorRegistry()
    request_count = Counter(
        "theeye_http_request_count_total",
        "HTTP requests handled by TheEye services",
        ("service", "method", "path", "status"),
        registry=registry,
    )
    request_latency = Histogram(
        "theeye_http_request_latency_seconds",
        "HTTP request latency for TheEye services",
        ("service", "method", "path"),
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=registry,
    )
    request_errors = Counter(
        "theeye_http_request_errors_total",
        "HTTP 5xx responses and unhandled exceptions in TheEye services",
        ("service", "method", "path"),
        registry=registry,
    )
    queue_depth = Gauge(
        "theeye_queue_depth",
        "In-process async work queue depth by service",
        ("service",),
        registry=registry,
    )
    service_info = Gauge(
        "theeye_service_info",
        "Static service identity for TheEye services",
        ("service",),
        registry=registry,
    )
    queue_depth.labels(service="risk-service").set(0)
    service_info.labels(service="risk-service").set(1)

    @app.middleware("http")
    async def prometheus_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        status = "500"
        failed = False
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        except Exception:
            failed = True
            raise
        finally:
            route = request.scope.get("route")
            path = str(getattr(route, "path", request.url.path))
            request_count.labels("risk-service", request.method, path, status).inc()
            request_latency.labels("risk-service", request.method, path).observe(
                time.perf_counter() - started,
            )
            if failed or status.startswith("5"):
                request_errors.labels("risk-service", request.method, path).inc()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "risk-service"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/validate-order")
    async def validate_order_endpoint(body: ValidateOrderBody) -> dict[str, object]:
        request = risk_pb2.RiskCheckRequest(
            portfolio_id=body.portfolio_id,
            instrument_id=body.instrument_id,
            side=body.side,
            qty=body.qty,
            limit_price=body.limit_price,
            order_intent=body.order_intent,
            sector=body.sector,
            cluster=body.cluster,
        )
        result = await validate_order_request(validator, request)
        return {
            "approved": result.approved,
            "outcome": result.outcome.name,
            "reason": result.reason,
            "failed_checks": result.failed_checks,
            "metrics": result.metrics,
        }

    @app.post("/v1/compute-portfolio-metrics")
    async def compute_metrics_endpoint(body: dict[str, str]) -> dict[str, float | str]:
        metrics = await compute_portfolio_metrics_request(body["portfolio_id"])
        return {
            "portfolio_id": metrics.portfolio_id,
            "var_95": metrics.var_95,
            "cvar_95": metrics.cvar_95,
            "max_drawdown": metrics.max_drawdown,
            "gross_exposure": metrics.gross_exposure,
            "net_exposure": metrics.net_exposure,
            "beta_spy": metrics.beta_spy,
            "concentration_hhi": metrics.concentration_hhi,
        }

    return app


async def serve_grpc(validator: OrderRiskValidator) -> grpc.aio.Server:
    """Start the gRPC server."""
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    risk_pb2_grpc.add_RiskServicer_to_server(RiskServicer(validator), server)
    listen = f"{_GRPC_HOST}:{_GRPC_PORT}"
    server.add_insecure_port(listen)
    await server.start()
    log.info("risk_grpc_started", listen=listen)
    return server


async def run_servers() -> None:
    """Run gRPC and HTTP servers concurrently."""
    validator = build_validator()
    grpc_server = await serve_grpc(validator)
    config = uvicorn.Config(
        create_http_app(validator),
        host=_HTTP_HOST,
        port=_HTTP_PORT,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(config)
    http_task = asyncio.create_task(uvicorn_server.serve())
    try:
        await grpc_server.wait_for_termination()
    finally:
        http_task.cancel()


def main() -> None:
    """Entrypoint for ``python -m risk_service``."""
    asyncio.run(run_servers())
