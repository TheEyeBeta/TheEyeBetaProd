"""OrderManager — Python orchestration over zinc_native.oms kernels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from oms.audit import insert_audit_log
from oms.db import fetch_order_row, insert_execution, persist_order_state, upsert_position
from oms.status_map import DB_TO_OMS, OMS_TO_DB, leg_id
from zinc_native import oms

log = structlog.get_logger()


@dataclass
class TransitionSnapshot:
    """Result of one state-machine transition."""

    order_id: str
    status: str
    filled_qty: float
    ok: bool
    error: str | None = None


class OrderManager:
    """Wrap ``StateMachine`` and ``PositionTracker`` with Postgres persistence."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._orders: dict[str, oms.Order] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._tracker = oms.PositionTracker()

    def _to_native(self, row: dict[str, Any]) -> oms.Order:
        order = oms.Order(
            order_id=row["id"],
            quantity=int(row["qty"]),
        )
        order.status = DB_TO_OMS[row["status"]]
        order.filled_quantity = int(row["filled_qty"])
        return order

    async def register_proposed(self, order_id: str) -> TransitionSnapshot:
        """Load a proposed order into the in-memory state machine cache."""
        row = await fetch_order_row(self._dsn, order_id)
        native = self._to_native(row)
        self._orders[order_id] = native
        self._meta[order_id] = row
        log.info("order_registered", order_id=order_id, status=row["status"])
        return TransitionSnapshot(
            order_id=order_id,
            status=row["status"],
            filled_qty=float(native.filled_quantity),
            ok=True,
        )

    async def approve(
        self,
        order_id: str,
        *,
        approved_by: str = "operator",
    ) -> list[TransitionSnapshot]:
        """Approve then auto-submit an order (pending → approved → submitted)."""
        await self._ensure_loaded(order_id)
        snapshots: list[TransitionSnapshot] = []
        snapshots.append(
            await self._apply_event(order_id, oms.Event.Approve, approved_by=approved_by),
        )
        if snapshots[-1].ok:
            snapshots.append(
                await self._apply_event(order_id, oms.Event.Submit, mark_submitted=True),
            )
        return snapshots

    async def handle_broker_accept(self, order_id: str) -> TransitionSnapshot:
        """Transition submitted → accepted (broker ack)."""
        await self._ensure_loaded(order_id)
        return await self._apply_event(order_id, oms.Event.Accept)

    async def handle_fill(
        self,
        order_id: str,
        *,
        qty: float,
        price: float,
        commission: float = 0.0,
        raw: dict[str, Any] | None = None,
    ) -> TransitionSnapshot:
        """Apply a broker fill, persist execution, and update positions."""
        await self._ensure_loaded(order_id)
        row = self._meta[order_id]
        native = self._orders[order_id]
        if native.status == oms.OrderStatus.Submitted:
            accept = await self._apply_event(order_id, oms.Event.Accept)
            if not accept.ok:
                return accept

        remaining = native.quantity - native.filled_quantity
        fill_qty = int(min(qty, max(remaining, 0)))
        if fill_qty <= 0:
            msg = f"no remaining quantity for order {order_id}"
            raise ValueError(msg)

        event = oms.Event.Fill if fill_qty >= remaining else oms.Event.PartialFill
        snapshot = await self._apply_event(order_id, event, fill_quantity=fill_qty)

        signed = fill_qty if row["side"].lower() == "buy" else -fill_qty
        leg = leg_id(row["portfolio_id"], int(row["instrument_id"]))
        self._tracker.apply_fill(leg, signed)

        avg_price = self._weighted_avg_price(native, row, price, fill_qty)
        row["avg_fill_price"] = avg_price
        await insert_execution(
            self._dsn,
            order_id=order_id,
            qty=float(fill_qty),
            price=price,
            commission=commission,
            raw=raw,
        )
        await upsert_position(
            self._dsn,
            portfolio_id=row["portfolio_id"],
            instrument_id=int(row["instrument_id"]),
            qty_delta=float(signed),
            fill_price=price,
        )
        await insert_audit_log(
            self._dsn,
            actor="broker-adapter-alpaca",
            action="order.fill",
            entity_type="order",
            entity_id=order_id,
            payload={
                "qty": fill_qty,
                "price": price,
                "status": snapshot.status,
                "commission": commission,
            },
        )
        await persist_order_state(
            self._dsn,
            order_id=order_id,
            status=snapshot.status,
            filled_qty=float(native.filled_quantity),
            avg_fill_price=avg_price,
        )
        return snapshot

    async def _ensure_loaded(self, order_id: str) -> None:
        if order_id not in self._orders:
            await self.register_proposed(order_id)

    async def _apply_event(
        self,
        order_id: str,
        event: oms.Event,
        *,
        fill_quantity: int = 0,
        approved_by: str | None = None,
        mark_submitted: bool = False,
    ) -> TransitionSnapshot:
        native = self._orders[order_id]
        result = oms.StateMachine.transition(native, event, fill_quantity)
        if not result.ok:
            detail = f"{result.error.code} from {result.error.from_status} on {result.error.event}"
            log.warning("order_transition_failed", order_id=order_id, detail=detail)
            return TransitionSnapshot(
                order_id=order_id,
                status=OMS_TO_DB.get(native.status, "unknown"),
                filled_qty=float(native.filled_quantity),
                ok=False,
                error=detail,
            )

        status = OMS_TO_DB[native.status]
        avg_price = self._meta[order_id].get("avg_fill_price")
        await persist_order_state(
            self._dsn,
            order_id=order_id,
            status=status,
            filled_qty=float(native.filled_quantity),
            avg_fill_price=avg_price,
            approved_by=approved_by,
            mark_submitted=mark_submitted,
        )
        self._meta[order_id]["status"] = status
        self._meta[order_id]["filled_qty"] = float(native.filled_quantity)
        log.info(
            "order_transition_ok",
            order_id=order_id,
            status=status,
            transition_event=str(event),
        )
        return TransitionSnapshot(
            order_id=order_id,
            status=status,
            filled_qty=float(native.filled_quantity),
            ok=True,
        )

    @staticmethod
    def _weighted_avg_price(
        native: oms.Order,
        meta: dict[str, Any],
        price: float,
        fill_qty: int,
    ) -> float:
        prev_filled = native.filled_quantity - fill_qty
        if prev_filled <= 0:
            return price
        prev_avg = float(meta.get("avg_fill_price") or price)
        total = (prev_avg * prev_filled) + (price * fill_qty)
        return total / native.filled_quantity

    def tracker_net(self, portfolio_id: str, instrument_id: int) -> int:
        """Return in-memory net position for tests."""
        return self._tracker.leg_position(leg_id(portfolio_id, instrument_id))
