"""Phase 9 OMS acceptance: Alpaca paper market order end-to-end."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from broker_adapter_alpaca.adapter import AlpacaAdapter  # noqa: E402
from broker_adapter_alpaca.settings import Settings as BrokerSettings  # noqa: E402
from zinc_schemas.broker_base import SubmitOrderRequest  # noqa: E402
from oms.audit import count_audit_trail, insert_audit_log
from oms.db import (
    fetch_first_portfolio_id,
    fetch_local_position_qty,
    insert_pending_order,
    resolve_instrument_id,
)
from oms.state import OrderManager


def _pg_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.skip("DATABASE_URL not set")
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def _alpaca_ready() -> bool:
    if not os.environ.get("ALPACA_API_KEY") or not os.environ.get("ALPACA_SECRET_KEY"):
        return False
    paper = os.environ.get("ALPACA_PAPER", "true").strip().lower()
    return paper in {"1", "true", "yes"}


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_paper_market_order_fills_and_reconciles_positions() -> None:
    """Submit 1-share market buy on Alpaca paper; assert DB matches broker and audit trail."""
    if not _alpaca_ready():
        pytest.skip("Alpaca paper credentials not configured")

    dsn = _pg_dsn()
    broker_settings = BrokerSettings()
    broker = AlpacaBrokerClient(broker_settings)

    portfolio_id = await fetch_first_portfolio_id(dsn)
    instrument_id = await resolve_instrument_id(dsn, "AAPL")
    symbol = "AAPL"
    qty = 1.0

    order_id = await insert_pending_order(
        dsn,
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        side="buy",
        qty=qty,
        order_id=str(uuid4()),
    )
    broker_before = {
        p["symbol"]: float(p["qty"]) for p in broker.list_positions() if p["symbol"] == symbol
    }
    local_before = await fetch_local_position_qty(dsn, portfolio_id, symbol)

    manager = OrderManager(dsn)
    snapshots = await manager.approve(order_id, approved_by="e2e-smoke")
    assert snapshots[-1].ok and snapshots[-1].status == "submitted"
    await insert_audit_log(
        dsn,
        actor="e2e-smoke",
        action="order.approve",
        entity_type="order",
        entity_id=order_id,
        payload={"status": snapshots[-1].status, "approved_by": "e2e-smoke"},
    )

    submit_result = broker.submit_order(
        SubmitOrderRequest(
            order_id=order_id,
            symbol=symbol,
            side="buy",
            qty=qty,
        ),
    )
    client_order_id = submit_result.client_order_id

    filled: dict | None = None
    for _ in range(40):
        await asyncio.sleep(0.5)
        latest = broker.get_order_by_client_id(client_order_id)
        if latest and latest.get("status") == "filled" and float(latest["filled_qty"]) >= qty:
            filled = latest
            break

    assert filled is not None, "Alpaca paper order did not fill in time"

    fill_snapshot = await manager.handle_fill(
        order_id,
        qty=float(filled["filled_qty"]),
        price=float(filled.get("filled_avg_price") or 0.0),
        commission=0.0,
        raw=filled,
    )
    assert fill_snapshot.ok and fill_snapshot.status == "filled"

    broker_after = float(
        next(p["qty"] for p in broker.list_positions() if p["symbol"] == symbol),
    )
    local_after = await fetch_local_position_qty(dsn, portfolio_id, symbol)
    broker_delta = broker_after - broker_before.get(symbol, 0.0)
    local_delta = local_after - local_before
    assert abs(broker_delta - qty) < 1e-4
    assert abs(local_delta - qty) < 1e-4
    assert abs(broker_after - local_after) < 1e-4

    trail_count = await count_audit_trail(dsn, order_id)
    assert trail_count >= 2
