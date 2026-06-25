"""Blotter orchestration for orders, broker, and OMS."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import structlog
from audit_log import write_audit_log
from blotter_control.client import (
    broker_health,
    broker_orders,
    broker_positions,
    oms_health,
    oms_resolve_reconciliation,
)
from blotter_control.reconciliation import diff_orders, diff_positions
from blotter_control.registry import (
    BROKER_TEST_GAP,
    CANCEL_BROKER_GAP,
    RECONCILIATION_PERSIST_GAP,
    REPLACE_BROKER_GAP,
    BlotterControlGap,
)
from blotter_control.repository import BlotterRepository
from settings import Settings
from trading_control.probes import oms_submissions_paused
from zinc_schemas.admin_dto import (
    BlotterControlGapEntry,
    BrokerAccountResponse,
    BrokerFillEntry,
    BrokerFillsResponse,
    BrokerOrdersResponse,
    BrokerPositionEntry,
    BrokerPositionsResponse,
    BrokerStatusResponse,
    BrokerTestConnectionResponse,
    OmsReconciliationResolveResponse,
    OmsReconciliationResponse,
    OmsStatusResponse,
    OrderEventEntry,
    OrderEventsResponse,
    OrderListResponse,
    OrderReplaceRequest,
    ReplaceOrderResponse,
)

log = structlog.get_logger()


class BlotterService:
    """Trading visibility and controlled mutations."""

    def __init__(self, conn: Any, settings: Settings, *, redis: object | None = None) -> None:
        self._conn = conn
        self._settings = settings
        self._redis = redis
        self._repo = BlotterRepository(conn)

    def _gaps(self) -> list[BlotterControlGapEntry]:
        gaps: list[BlotterControlGap] = [
            CANCEL_BROKER_GAP,
            REPLACE_BROKER_GAP,
            RECONCILIATION_PERSIST_GAP,
            BROKER_TEST_GAP,
        ]
        return [BlotterControlGapEntry(action=g.action, reason=g.reason) for g in gaps]

    async def list_orders(self, *, status: str | None = None, limit: int = 100) -> OrderListResponse:
        from blotter_control.orders_helpers import row_to_summary

        rows = await self._repo.list_orders(status=status, limit=limit)
        pending = sum(1 for row in rows if row["status"] == "pending_approval")
        live = sum(1 for row in rows if row["status"] in {"submitted", "accepted", "partially_filled"})
        return OrderListResponse(
            orders=[row_to_summary(row) for row in rows],
            total=len(rows),
            pending_count=pending,
            live_count=live,
            status_filter=status,
        )

    async def order_events(self, order_id: UUID) -> OrderEventsResponse:
        rows = await self._repo.order_events(order_id)
        return OrderEventsResponse(
            order_id=str(order_id),
            events=[
                OrderEventEntry(
                    source=str(row["source"]),
                    event_type=str(row["event_type"]),
                    actor=str(row.get("actor") or ""),
                    payload=row.get("payload") or {},
                    ts=row["ts"],
                )
                for row in rows
            ],
        )

    async def cancel_order(self, order_id: UUID, *, actor: str, reason: str) -> dict[str, Any]:
        row = await self._repo.cancel_order(order_id, actor=actor, reason=reason)
        if not row:
            msg = "Order cannot be cancelled in its current status"
            raise ValueError(msg)
        await self._repo.record_event(
            event_type="order_cancel",
            actor=actor,
            reason=reason,
            payload={"order_id": str(order_id), "advisory_only": True},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="cancel.order",
            entity_type="order",
            entity_id=str(order_id),
            payload={"reason": reason},
        )
        return row

    async def replace_order(
        self,
        order_id: UUID,
        body: OrderReplaceRequest,
        *,
        actor: str,
    ) -> ReplaceOrderResponse:
        qty = float(body.qty) if body.qty is not None else None
        limit_price = float(body.limit_price) if body.limit_price is not None else None
        row = await self._repo.replace_order(
            order_id,
            actor=actor,
            reason=body.reason,
            qty=qty,
            limit_price=limit_price,
        )
        if not row:
            msg = "Order cannot be replaced in its current status"
            raise ValueError(msg)
        await self._repo.record_event(
            event_type="order_replace",
            actor=actor,
            reason=body.reason,
            payload={"order_id": str(order_id), "qty": qty, "limit_price": limit_price},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="replace.order",
            entity_type="order",
            entity_id=str(order_id),
            payload={"reason": body.reason, "qty": qty, "limit_price": limit_price},
        )
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return ReplaceOrderResponse(
            id=row["id"],
            status=str(row["status"]),
            qty=Decimal(str(row["qty"])),
            limit_price=Decimal(str(row["limit_price"])) if row.get("limit_price") is not None else None,
            metadata=metadata if isinstance(metadata, dict) else {},
            audited=True,
        )

    async def broker_status(self) -> BrokerStatusResponse:
        mode = self._settings.broker_mode.strip().lower()
        reachable: bool | None = False
        health = "unknown"
        message = ""
        try:
            payload = await broker_health(self._settings)
            reachable = True
            health = "ready"
            message = f"mode={payload.get('mode', mode)}"
        except (httpx.HTTPError, OSError) as exc:
            message = str(exc)[:200]
        stale = await self._repo.positions_stale()
        state = await self._repo.get_state()
        return BrokerStatusResponse(
            broker_mode=mode,
            service_health=health,
            service_reachable=reachable,
            message=message,
            positions_stale=stale,
            last_test_at=state.get("last_broker_test_at"),
            last_test_ok=state.get("last_broker_test_ok"),
            control_gaps=self._gaps(),
            checked_at=BlotterRepository.utc_now(),
        )

    async def broker_account(self) -> BrokerAccountResponse:
        pid = await self._repo.default_portfolio_id()
        summary = await self._repo.account_summary(portfolio_id=pid)
        return BrokerAccountResponse(
            portfolio_id=str(summary.get("portfolio_id") or pid or ""),
            account_id=str(summary.get("id") or ""),
            external_id=str(summary.get("external_id") or ""),
            broker=str(summary.get("broker") or ""),
            mode=str(summary.get("mode") or self._settings.broker_mode),
            base_currency=str(summary.get("base_currency") or "USD"),
            status=str(summary.get("status") or "unknown"),
            portfolio_name=str(summary.get("portfolio_name") or ""),
        )

    async def broker_positions(self, *, source: str = "local") -> BrokerPositionsResponse:
        stale = await self._repo.positions_stale()
        broker_rows: list[dict[str, Any]] = []
        broker_reachable = False
        if source in {"broker", "both"}:
            try:
                broker_rows = await broker_positions(self._settings)
                broker_reachable = True
            except (httpx.HTTPError, OSError):
                broker_reachable = False
        local_rows = await self._repo.list_positions()
        return BrokerPositionsResponse(
            source=source,
            broker_reachable=broker_reachable,
            stale=stale,
            local=[
                BrokerPositionEntry(
                    symbol=str(row["symbol"]),
                    portfolio_id=str(row["portfolio_id"]),
                    qty=Decimal(str(row["qty"])),
                    avg_entry_price=Decimal(str(row["avg_entry_price"])),
                    market_value=(
                        Decimal(str(row["market_value"])) if row.get("market_value") is not None else None
                    ),
                    updated_at=row["updated_at"],
                )
                for row in local_rows
            ],
            broker=[
                BrokerPositionEntry(
                    symbol=str(row.get("symbol") or ""),
                    portfolio_id="",
                    qty=Decimal(str(row.get("qty") or 0)),
                    avg_entry_price=Decimal("0"),
                    market_value=None,
                    updated_at=BlotterRepository.utc_now(),
                )
                for row in broker_rows
            ],
        )

    async def broker_orders_proxy(self) -> BrokerOrdersResponse:
        try:
            rows = await broker_orders(self._settings)
            reachable = True
        except (httpx.HTTPError, OSError):
            rows = []
            reachable = False
        return BrokerOrdersResponse(
            broker_reachable=reachable,
            orders=rows,
        )

    async def broker_fills(self, *, limit: int = 100) -> BrokerFillsResponse:
        rows = await self._repo.list_executions(limit=limit)
        return BrokerFillsResponse(
            fills=[
                BrokerFillEntry(
                    id=int(row["id"]),
                    order_id=str(row["order_id"]),
                    client_order_id=str(row["client_order_id"]),
                    symbol=str(row["symbol"]),
                    ts=row["ts"],
                    qty=Decimal(str(row["qty"])),
                    price=Decimal(str(row["price"])),
                    commission=Decimal(str(row["commission"])),
                )
                for row in rows
            ],
        )

    async def test_connection(self, *, actor: str, reason: str) -> BrokerTestConnectionResponse:
        ok = False
        detail = ""
        try:
            payload = await broker_health(self._settings)
            ok = payload.get("status") == "ok"
            detail = str(payload.get("mode") or "ok")
        except (httpx.HTTPError, OSError) as exc:
            detail = str(exc)[:200]
        await self._repo.save_state(
            last_broker_test_at=BlotterRepository.utc_now(),
            last_broker_test_by=actor,
            last_broker_test_ok=ok,
        )
        await self._repo.record_event(
            event_type="broker_test",
            actor=actor,
            reason=reason,
            payload={"ok": ok, "detail": detail},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="broker.test_connection",
            entity_type="broker",
            entity_id="adapter",
            payload={"reason": reason, "ok": ok},
        )
        return BrokerTestConnectionResponse(ok=ok, detail=detail, audited=True, reason=reason)

    async def oms_status(self) -> OmsStatusResponse:
        paused_redis = await oms_submissions_paused(self._redis)
        paused_http = False
        reachable: bool | None = False
        health = "unknown"
        try:
            payload = await oms_health(self._settings)
            reachable = True
            health = "ready"
            paused_http = bool(payload.get("submissions_paused"))
        except (httpx.HTTPError, OSError):
            health = "unknown"
        return OmsStatusResponse(
            service_health=health,
            service_reachable=reachable,
            submissions_paused=paused_redis or paused_http,
            checked_at=BlotterRepository.utc_now(),
        )

    async def reconciliation_status(self) -> OmsReconciliationResponse:
        paused = await oms_submissions_paused(self._redis)
        local_positions = await self._repo.local_positions_for_recon()
        local_orders = await self._repo.local_active_orders_for_recon()
        broker_pos: list[dict[str, Any]] = []
        broker_ord: list[dict[str, Any]] = []
        broker_reachable = False
        try:
            broker_pos = await broker_positions(self._settings)
            broker_ord = await broker_orders(self._settings)
            broker_reachable = True
        except (httpx.HTTPError, OSError):
            broker_reachable = False
        position_drifts = diff_positions(broker_pos, local_positions) if broker_reachable else []
        order_drifts = diff_orders(broker_ord, local_orders) if broker_reachable else []
        drifts = position_drifts + order_drifts
        state = await self._repo.get_state()
        return OmsReconciliationResponse(
            submissions_paused=paused,
            broker_reachable=broker_reachable,
            drift_count=len(drifts),
            position_drifts=position_drifts,
            order_drifts=order_drifts,
            last_checked_at=state.get("last_reconciliation_at"),
            last_checked_by=state.get("last_reconciliation_by"),
            control_gaps=[
                BlotterControlGapEntry(
                    action=RECONCILIATION_PERSIST_GAP.action,
                    reason=RECONCILIATION_PERSIST_GAP.reason,
                ),
            ],
            checked_at=BlotterRepository.utc_now(),
        )

    async def resolve_reconciliation(self, *, actor: str, reason: str) -> OmsReconciliationResolveResponse:
        mode = "remote"
        try:
            await oms_resolve_reconciliation(self._settings)
        except (httpx.HTTPError, OSError):
            mode = "local"
            if self._redis is not None:
                from trading_control.probes import set_oms_paused

                await set_oms_paused(self._redis, paused=False)
        recon = await self.reconciliation_status()
        await self._repo.save_state(
            last_reconciliation_at=BlotterRepository.utc_now(),
            last_reconciliation_by=actor,
            last_drift_count=recon.drift_count,
        )
        await self._repo.record_event(
            event_type="reconciliation_resolve",
            actor=actor,
            reason=reason,
            payload={"mode": mode, "drift_count": recon.drift_count},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="oms.reconciliation.resolve",
            entity_type="oms",
            entity_id="reconciliation",
            payload={"reason": reason, "mode": mode},
        )
        return OmsReconciliationResolveResponse(
            mode=mode,
            submissions_paused=(await self.oms_status()).submissions_paused,
            audited=True,
            reason=reason,
        )
