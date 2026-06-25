"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from oms.audit import insert_audit_log
from oms.consumer import OmsEventConsumer
from oms.db import fetch_order_row, persist_order_rejection
from oms.reconciliation import ReconciliationLoop
from oms.settings import Settings
from oms.state import OrderManager
from oms.submission_gate import SubmissionGate
from oms.validation_gate import check_compliance, check_risk

log = structlog.get_logger()


class ApproveBody(BaseModel):
    """Optional operator metadata for approval."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(default="operator")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the OMS FastAPI application."""
    cfg = settings or Settings()
    manager = OrderManager(cfg.pg_dsn())
    gate = SubmissionGate(cfg.redis_url or None)
    consumer = OmsEventConsumer(cfg.nats_url, manager)
    reconciliation = ReconciliationLoop(
        cfg.pg_dsn(),
        cfg.broker_adapter_url,
        cfg.nats_url,
        gate,
        interval_seconds=cfg.reconciliation_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            await consumer.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_nats_consumer_unavailable", error=str(exc))
        try:
            await reconciliation.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_reconciliation_unavailable", error=str(exc))
        log.info("oms_started", host=cfg.host, port=cfg.port)
        yield
        await reconciliation.stop()
        await consumer.stop()
        log.info("oms_stopped")

    app = FastAPI(title="oms", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, object]:
        paused = await gate.is_paused()
        return {
            "status": "ok",
            "service": cfg.service_name,
            "submissions_paused": paused,
        }

    @app.post("/oms/reconciliation/resolve")
    async def resolve_reconciliation() -> dict[str, str]:
        """Manually clear reconciliation pause after drift is fixed."""
        await gate.resume()
        return {"status": "resumed"}

    @app.post("/oms/orders/{order_id}/approve")
    async def approve_order(order_id: UUID, body: ApproveBody | None = None) -> dict[str, object]:
        """Approve a pending order, submit it, and notify the broker adapter."""
        if await gate.is_paused():
            raise HTTPException(
                status_code=423,
                detail="submissions paused pending reconciliation resolution",
            )
        approved_by = (body or ApproveBody()).approved_by
        try:
            row = await fetch_order_row(cfg.pg_dsn(), str(order_id))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        limit_price = row["limit_price"] if row["limit_price"] is not None else 100.0
        gate_calls = (
            ("risk_service", cfg.risk_service_http_url, check_risk),
            ("compliance_service", cfg.compliance_service_http_url, check_compliance),
        )
        for source, base_url, gate_fn in gate_calls:
            result = await gate_fn(
                base_url,
                portfolio_id=row["portfolio_id"],
                instrument_id=row["instrument_id"],
                side=row["side"],
                qty=row["qty"],
                limit_price=limit_price,
            )
            if not result.get("approved", True):
                reason = str(result.get("reason") or f"{source} rejected order")
                await persist_order_rejection(cfg.pg_dsn(), order_id=str(order_id), reason=reason)
                await insert_audit_log(
                    cfg.pg_dsn(),
                    actor=approved_by,
                    action="order.reject",
                    entity_type="order",
                    entity_id=str(order_id),
                    payload={"source": source, "reason": reason},
                )
                raise HTTPException(status_code=422, detail=reason)

        try:
            snapshots = await manager.approve(str(order_id), approved_by=approved_by)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not snapshots or not snapshots[0].ok:
            detail = snapshots[0].error if snapshots else "approve failed"
            raise HTTPException(status_code=409, detail=detail)

        await insert_audit_log(
            cfg.pg_dsn(),
            actor=approved_by,
            action="order.approve",
            entity_type="order",
            entity_id=str(order_id),
            payload={
                "portfolio_id": row["portfolio_id"],
                "transitions": [snap.status for snap in snapshots],
            },
        )

        payload = {
            "order_id": str(order_id),
            "portfolio_id": row["portfolio_id"],
            "instrument_id": row["instrument_id"],
            "side": row["side"],
            "qty": row["qty"],
            "status": snapshots[-1].status,
            "approved_by": approved_by,
        }
        if snapshots[-1].ok:
            try:
                await consumer.publish_approved(str(order_id), payload)
            except Exception as exc:  # noqa: BLE001
                log.warning("oms_approved_publish_failed", order_id=str(order_id), error=str(exc))

        return {
            "order_id": str(order_id),
            "status": snapshots[-1].status,
            "transitions": [
                {"status": snap.status, "ok": snap.ok, "error": snap.error} for snap in snapshots
            ],
        }

    return app
