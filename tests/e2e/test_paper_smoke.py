"""End-to-end paper-trade smoke test.

Exercises the full two-loop pipeline against a live stack and Alpaca paper
trading.  Must pass 7 consecutive nights to graduate to the 90-day paper
validation period.

Requires (all satisfied by the nightly CI workflow or ``make up`` locally):
  - DATABASE_URL, REDIS_URL, NATS_URL env vars
  - OMS, audit-service, master-orchestrator, broker-adapter running
  - ALPACA_API_KEY_PAPER, ALPACA_API_SECRET_PAPER env vars
  - ``require_stack`` and ``require_alpaca_credentials`` fixtures (conftest.py)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, date, datetime
from uuid import UUID

import asyncpg
import httpx
import nats
import pytest
from redis.asyncio import Redis

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_NATS_URL = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
_OMS_URL = os.environ.get("OMS_URL", "http://127.0.0.1:8009")
_AUDIT_URL = os.environ.get("AUDIT_URL", "http://127.0.0.1:7110")

_POLL_INTERVAL = 5.0
_PENDING_TIMEOUT = 360.0
_FILL_TIMEOUT = 180.0


def _clean_dsn(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+psycopg2://", "postgresql://", 1)
    )


async def _poll_pending_order(
    pool: asyncpg.Pool,
    after: datetime,
    *,
    timeout: float,
) -> str | None:
    """Return the first pending_approval order id created after ``after``."""
    try:
        async with asyncio.timeout(timeout):
            while True:
                row = await pool.fetchrow(
                    """
                    SELECT id::text
                      FROM theeyebeta.orders
                     WHERE status = 'pending_approval'
                       AND created_at >= $1
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    after,
                )
                if row:
                    return str(row["id"])
                await asyncio.sleep(_POLL_INTERVAL)
    except TimeoutError:
        return None


async def _wait_for_fill(
    pool: asyncpg.Pool,
    order_id: str,
    *,
    timeout: float,
) -> bool:
    """Poll until the order is filled; return True on success."""
    try:
        async with asyncio.timeout(timeout):
            while True:
                row = await pool.fetchrow(
                    "SELECT status FROM theeyebeta.orders WHERE id = $1",
                    UUID(order_id),
                )
                if row and str(row["status"]) in {"filled", "partial_fill"}:
                    return True
                await asyncio.sleep(_POLL_INTERVAL)
    except TimeoutError:
        return False


async def _fetch_order(pool: asyncpg.Pool, order_id: str) -> dict[str, object]:
    row = await pool.fetchrow(
        """
        SELECT id::text, portfolio_id::text, instrument_id,
               side, qty, status, filled_qty
          FROM theeyebeta.orders
         WHERE id = $1
        """,
        UUID(order_id),
    )
    return dict(row) if row else {}


async def _fetch_position_qty(
    pool: asyncpg.Pool,
    portfolio_id: str,
    instrument_id: int,
) -> float:
    row = await pool.fetchrow(
        """
        SELECT qty
          FROM theeyebeta.positions
         WHERE portfolio_id = $1 AND instrument_id = $2
        """,
        UUID(portfolio_id),
        instrument_id,
    )
    return float(row["qty"]) if row else 0.0


async def _resolve_symbol(pool: asyncpg.Pool, instrument_id: int) -> str | None:
    row = await pool.fetchrow(
        "SELECT symbol FROM theeyebeta.instruments WHERE id = $1",
        instrument_id,
    )
    return str(row["symbol"]) if row else None


def _alpaca_cleanup(api_key: str, api_secret: str) -> None:
    """Cancel all open orders and flatten all positions on the paper account."""
    from alpaca.trading.client import TradingClient  # noqa: PLC0415

    TradingClient(api_key, api_secret, paper=True).close_all_positions(cancel_orders=True)


@pytest.mark.smoke
async def test_paper_trade_full_stack(
    paper_smoke_date: date,
    fast_forward_snapshot: tuple[str, str],
) -> None:
    """Full two-loop smoke: ingest → pack → orchestrate → approve → fill → audit."""
    assert _DATABASE_URL, "DATABASE_URL must be set for smoke tests"

    dsn = _clean_dsn(_DATABASE_URL)
    run_start = datetime.now(tz=UTC)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    try:
        # ── Step 1: clear Redis idempotency lock so MO runs fresh ────────────
        redis = Redis.from_url(_REDIS_URL, decode_responses=True)
        await redis.delete(f"orchestrator:trio:US:{paper_smoke_date.isoformat()}")
        await redis.aclose()

        # ── Step 2: publish snapshots.packaged.US.{date} to trigger MO ───────
        snapshot_id, blob_uri = fast_forward_snapshot
        nc = await nats.connect(_NATS_URL)
        await nc.publish(
            f"snapshots.packaged.US.{paper_smoke_date.isoformat()}",
            json.dumps(
                {
                    "market": "US",
                    "date": paper_smoke_date.isoformat(),
                    "snapshot_id": snapshot_id,
                    "blob_uri": blob_uri,
                    "schema_version": 1,
                }
            ).encode(),
        )
        await nc.flush()
        await nc.drain()

        # ── Step 3: wait for MO to write a pending_approval order ─────────────
        order_id = await _poll_pending_order(pool, run_start, timeout=_PENDING_TIMEOUT)
        assert order_id, (
            f"No pending_approval order appeared within {_PENDING_TIMEOUT}s — "
            "check master-orchestrator logs for errors"
        )

        # ── Step 4: assert the order is genuinely pending_approval ────────────
        order = await _fetch_order(pool, order_id)
        assert order["status"] == "pending_approval", (
            f"Expected pending_approval, got {order['status']!r}"
        )

        # ── Step 5: approve via OMS API ───────────────────────────────────────
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                f"{_OMS_URL}/oms/orders/{order_id}/approve",
                json={"approved_by": "paper-smoke-test"},
            )
        assert resp.status_code == 200, f"OMS approve returned {resp.status_code}: {resp.text}"

        # ── Step 6: wait for fill from Alpaca paper ────────────────────────────
        filled = await _wait_for_fill(pool, order_id, timeout=_FILL_TIMEOUT)
        assert filled, (
            f"Order {order_id} not filled within {_FILL_TIMEOUT}s — "
            "check broker-adapter-alpaca logs"
        )

        # ── Step 7: assert position row updated ───────────────────────────────
        order = await _fetch_order(pool, order_id)
        assert str(order["status"]) in {
            "filled",
            "partial_fill",
        }, f"Unexpected final status: {order['status']!r}"
        qty = await _fetch_position_qty(
            pool,
            str(order["portfolio_id"]),
            int(order["instrument_id"]),  # type: ignore[arg-type]
        )
        assert qty != 0.0, "positions row not updated after fill"

        # ── Step 8: audit hash-chain verification ────────────────────────────
        run_end = datetime.now(tz=UTC)
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.get(
                f"{_AUDIT_URL}/audit/verify",
                params={
                    "from": run_start.isoformat(),
                    "to": run_end.isoformat(),
                },
            )
        assert resp.status_code == 200, f"Audit verify returned {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "OK", (
            f"Audit chain broken — first_bad_row_id={body.get('first_bad_row_id')}, "
            f"detail={body.get('detail')}"
        )

    finally:
        await pool.close()
        # ── Step 9: flatten paper account so subsequent runs start clean ──────
        api_key = os.environ.get("ALPACA_API_KEY_PAPER", "")
        api_secret = os.environ.get("ALPACA_API_SECRET_PAPER", "")
        if api_key and api_secret:
            await asyncio.to_thread(_alpaca_cleanup, api_key, api_secret)
