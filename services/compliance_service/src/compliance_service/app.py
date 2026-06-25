"""Compliance-service application — gRPC servicer and HTTP bridge."""

from __future__ import annotations

import asyncio
import os
from concurrent import futures

import grpc
import structlog
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from compliance_service.db import (
    load_active_holds_and_overrides,
    load_check_context,
    persist_compliance_checks,
    reject_order_if_blocked,
)
from compliance_service.engine import ComplianceEngine, apply_admin_overrides_and_holds
from compliance_service.models import (
    ComplianceCheckResult,
    ComplianceOutcome,
    OrderProposal,
)
from zinc_proto import compliance_pb2, compliance_pb2_grpc

log = structlog.get_logger()

_GRPC_HOST = os.environ.get("COMPLIANCE_SERVICE_GRPC_HOST", "127.0.0.1")
_GRPC_PORT = int(os.environ.get("COMPLIANCE_SERVICE_GRPC_PORT", "7070"))
_HTTP_HOST = os.environ.get("COMPLIANCE_SERVICE_HTTP_HOST", "127.0.0.1")
_HTTP_PORT = int(os.environ.get("COMPLIANCE_SERVICE_HTTP_PORT", "8008"))


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


class CheckOrderBody(BaseModel):
    """HTTP bridge body for pre-trade compliance checks."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    instrument_id: int
    side: str
    qty: float
    limit_price: float = 100.0
    market: str = "US"
    order_id: str | None = None
    symbol: str | None = None


def build_engine() -> ComplianceEngine:
    """Return the default five-rule engine."""
    return ComplianceEngine()


async def check_order_request(
    engine: ComplianceEngine,
    request: compliance_pb2.ComplianceCheckRequest,
) -> ComplianceCheckResult:
    """Run compliance checks, persist rows, and reject blocked orders."""
    dsn = _db_url()
    portfolio, mandate, symbol = await load_check_context(
        dsn,
        portfolio_id=request.portfolio_id,
        instrument_id=int(request.instrument_id),
        order_id=request.order_id or None,
    )
    order = OrderProposal(
        instrument_id=int(request.instrument_id),
        symbol=request.symbol or symbol,
        side=request.side,
        qty=float(request.qty),
        limit_price=float(request.limit_price or 100.0),
        market=request.market or "US",
        order_id=request.order_id or None,
    )
    result = engine.check(order, portfolio, mandate)
    holds, overrides_by_rule = await load_active_holds_and_overrides(
        dsn,
        portfolio_id=request.portfolio_id,
        account_id=portfolio.account_id,
        symbol=order.symbol,
        instrument_id=order.instrument_id,
    )
    result = apply_admin_overrides_and_holds(
        result,
        holds=holds,
        overrides_by_rule=overrides_by_rule,
    )
    await persist_compliance_checks(
        dsn,
        portfolio_id=request.portfolio_id,
        order_id=order.order_id,
        results=result.rule_results,
    )
    await reject_order_if_blocked(
        dsn,
        order_id=order.order_id,
        outcome=result.outcome,
        rule_id=result.blocking_rule_id,
    )
    return result


def to_proto_decision(result: ComplianceCheckResult) -> compliance_pb2.ComplianceDecision:
    """Map internal result to protobuf response."""
    outcome_map = {
        ComplianceOutcome.PASS: compliance_pb2.PASS,
        ComplianceOutcome.WARN: compliance_pb2.WARN,
        ComplianceOutcome.BLOCK: compliance_pb2.BLOCK,
    }
    rule_results = [
        compliance_pb2.RuleOutcome(
            rule_id=r.rule_id,
            outcome=outcome_map[r.outcome],
            detail=r.detail,
        )
        for r in result.rule_results
    ]
    return compliance_pb2.ComplianceDecision(
        outcome=outcome_map[result.outcome],
        reason=result.reason,
        rule_results=rule_results,
        failed_rules=result.failed_rules,
        approved=result.approved,
    )


class ComplianceServicer(compliance_pb2_grpc.ComplianceServicer):
    """gRPC servicer for ``CheckOrder``."""

    def __init__(self, engine: ComplianceEngine) -> None:
        self._engine = engine

    async def CheckOrder(  # noqa: N802
        self,
        request: compliance_pb2.ComplianceCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> compliance_pb2.ComplianceDecision:
        _ = context
        result = await check_order_request(self._engine, request)
        return to_proto_decision(result)


def create_http_app(engine: ComplianceEngine) -> FastAPI:
    """FastAPI app exposing health and HTTP compliance bridge."""
    app = FastAPI(title="compliance-service", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "compliance-service"}

    async def _handle(body: CheckOrderBody) -> dict[str, object]:
        request = compliance_pb2.ComplianceCheckRequest(
            order_id=body.order_id or "",
            portfolio_id=body.portfolio_id,
            instrument_id=body.instrument_id,
            symbol=body.symbol or "",
            side=body.side,
            qty=body.qty,
            limit_price=body.limit_price,
            market=body.market,
        )
        result = await check_order_request(engine, request)
        return {
            "approved": result.approved,
            "outcome": result.outcome.name,
            "reason": result.reason,
            "failed_checks": result.failed_rules,
            "failed_rules": result.failed_rules,
            "rule_results": [
                {
                    "rule_id": r.rule_id,
                    "outcome": r.outcome.name,
                    "detail": r.detail,
                }
                for r in result.rule_results
            ],
        }

    @app.post("/v1/check-order")
    async def check_order_endpoint(body: CheckOrderBody) -> dict[str, object]:
        return await _handle(body)

    @app.post("/v1/validate-order")
    async def validate_order_endpoint(body: CheckOrderBody) -> dict[str, object]:
        """Alias for master-orchestrator HTTP client."""
        return await _handle(body)

    return app


async def serve_grpc(engine: ComplianceEngine) -> grpc.aio.Server:
    """Start the gRPC server."""
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    compliance_pb2_grpc.add_ComplianceServicer_to_server(ComplianceServicer(engine), server)
    listen = f"{_GRPC_HOST}:{_GRPC_PORT}"
    server.add_insecure_port(listen)
    await server.start()
    log.info("compliance_grpc_started", listen=listen)
    return server


async def run_servers() -> None:
    """Run gRPC and HTTP servers concurrently."""
    engine = build_engine()
    grpc_server = await serve_grpc(engine)
    config = uvicorn.Config(
        create_http_app(engine),
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
    """Entrypoint for ``python -m compliance_service``."""
    asyncio.run(run_servers())
