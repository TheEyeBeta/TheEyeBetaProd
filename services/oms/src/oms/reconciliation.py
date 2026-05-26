"""Periodic broker vs local reconciliation loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import nats
import structlog

from oms.broker_client import BrokerAdapterClient
from oms.submission_gate import SubmissionGate

log = structlog.get_logger()

BREACH_SUBJECT = "risk.breaches.reconciliation"
TERMINAL_STATUSES = frozenset(
    {"filled", "cancelled", "rejected", "expired"},
)
ACTIVE_STATUSES = frozenset(
    {
        "pending_approval",
        "approved",
        "submitted",
        "accepted",
        "partially_filled",
    },
)


class ReconciliationLoop:
    """Every ``interval_seconds``, compare broker state to Postgres."""

    def __init__(
        self,
        dsn: str,
        broker_url: str,
        nats_url: str,
        gate: SubmissionGate,
        *,
        interval_seconds: int = 180,
    ) -> None:
        self._dsn = dsn
        self._broker = BrokerAdapterClient(broker_url)
        self._nats_url = nats_url
        self._gate = gate
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._nc: nats.NATS | None = None

    async def start(self) -> None:
        """Start the background reconciliation task."""
        self._nc = await nats.connect(self._nats_url)
        self._task = asyncio.create_task(self._run(), name="oms-reconciliation")
        log.info("oms_reconciliation_started", interval_seconds=self._interval)

    async def stop(self) -> None:
        """Stop the background task."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None
        log.info("oms_reconciliation_stopped")

    async def run_once(self) -> dict[str, Any]:
        """Execute one reconciliation cycle (test hook)."""
        return await self._reconcile()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._reconcile()
            except Exception as exc:  # noqa: BLE001
                log.warning("oms_reconciliation_cycle_failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    async def _reconcile(self) -> dict[str, Any]:
        broker_positions = await self._broker.list_positions()
        broker_orders = await self._broker.list_orders()
        local_positions = await self._load_local_positions()
        local_orders = await self._load_local_orders()

        position_drifts = _diff_positions(broker_positions, local_positions)
        order_drifts = _diff_orders(broker_orders, local_orders)
        drifts = position_drifts + order_drifts

        if drifts:
            payload = {
                "breach_type": "reconciliation",
                "position_drifts": position_drifts,
                "order_drifts": order_drifts,
                "drift_count": len(drifts),
            }
            await self._publish_breach(payload)
            await self._gate.pause(reason="reconciliation drift detected")
            log.warning("oms_reconciliation_drift", drift_count=len(drifts))
            return {"ok": False, "drifts": drifts}

        if await self._gate.is_paused():
            await self._gate.resume()
        log.info("oms_reconciliation_ok")
        return {"ok": True, "drifts": []}

    async def _publish_breach(self, payload: dict[str, Any]) -> None:
        if self._nc is None:
            return
        await self._nc.publish(BREACH_SUBJECT, json.dumps(payload).encode())

    async def _load_local_positions(self) -> list[dict[str, Any]]:
        import psycopg  # noqa: PLC0415

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            cur = await conn.execute(
                """
                SELECT i.symbol, p.qty
                  FROM theeyebeta.positions p
                  JOIN theeyebeta.instruments i ON i.id = p.instrument_id
                """,
            )
            rows = await cur.fetchall()
        return [{"symbol": str(r[0]), "qty": float(r[1])} for r in rows]

    async def _load_local_orders(self) -> list[dict[str, Any]]:
        import psycopg  # noqa: PLC0415

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            cur = await conn.execute(
                """
                SELECT client_order_id, broker_order_id, status, filled_qty
                  FROM theeyebeta.orders
                 WHERE status = ANY(%s)
                """,
                (list(ACTIVE_STATUSES),),
            )
            rows = await cur.fetchall()
        return [
            {
                "client_order_id": str(r[0]),
                "broker_order_id": str(r[1] or ""),
                "status": str(r[2]),
                "filled_qty": float(r[3]),
            }
            for r in rows
        ]


def _diff_positions(
    broker: list[dict[str, Any]],
    local: list[dict[str, Any]],
    *,
    qty_tolerance: float = 1e-4,
) -> list[dict[str, Any]]:
    """Compare symbol → qty maps."""
    broker_map = {p["symbol"]: float(p["qty"]) for p in broker}
    local_map = {p["symbol"]: float(p["qty"]) for p in local}
    symbols = set(broker_map) | set(local_map)
    drifts: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        b_qty = broker_map.get(symbol, 0.0)
        l_qty = local_map.get(symbol, 0.0)
        if abs(b_qty - l_qty) > qty_tolerance:
            drifts.append(
                {
                    "kind": "position",
                    "symbol": symbol,
                    "broker_qty": b_qty,
                    "local_qty": l_qty,
                },
            )
    return drifts


def _diff_orders(
    broker: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flag active local orders missing on broker or qty mismatch."""
    broker_by_client = {
        str(o.get("client_order_id") or ""): o for o in broker if o.get("client_order_id")
    }
    drifts: list[dict[str, Any]] = []
    for local_order in local:
        client_id = local_order["client_order_id"]
        remote = broker_by_client.get(client_id)
        if remote is None:
            drifts.append(
                {
                    "kind": "order_missing_on_broker",
                    "client_order_id": client_id,
                    "local_status": local_order["status"],
                },
            )
            continue
        if abs(float(remote.get("filled_qty") or 0) - local_order["filled_qty"]) > 1e-4:
            drifts.append(
                {
                    "kind": "order_fill_qty",
                    "client_order_id": client_id,
                    "broker_filled_qty": float(remote.get("filled_qty") or 0),
                    "local_filled_qty": local_order["filled_qty"],
                },
            )
    return drifts
