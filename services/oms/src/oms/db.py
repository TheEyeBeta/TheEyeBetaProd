"""Postgres persistence for orders, executions, and positions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import structlog

log = structlog.get_logger()


async def fetch_order_row(dsn: str, order_id: str) -> dict[str, Any]:
    """Load one order row from Postgres."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT id, portfolio_id, instrument_id, side, qty, status, filled_qty,
                   avg_fill_price, limit_price
              FROM theeyebeta.orders
             WHERE id = %s
            """,
            (UUID(order_id),),
        )
        row = await cur.fetchone()
    if row is None:
        msg = f"order {order_id} not found"
        raise ValueError(msg)
    return {
        "id": str(row[0]),
        "portfolio_id": str(row[1]),
        "instrument_id": int(row[2]),
        "side": str(row[3]),
        "qty": float(row[4]),
        "status": str(row[5]),
        "filled_qty": float(row[6]),
        "avg_fill_price": float(row[7]) if row[7] is not None else None,
        "limit_price": float(row[8]) if row[8] is not None else None,
    }


async def persist_order_state(
    dsn: str,
    *,
    order_id: str,
    status: str,
    filled_qty: float,
    avg_fill_price: float | None = None,
    approved_by: str | None = None,
    mark_submitted: bool = False,
) -> None:
    """Update ``orders.status`` and fill aggregates after a state transition."""
    now = datetime.now(tz=UTC)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        if approved_by:
            await conn.execute(
                """
                UPDATE theeyebeta.orders
                   SET status = %s,
                       filled_qty = %s,
                       avg_fill_price = %s,
                       approved_by = %s,
                       approved_at = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
                (
                    status,
                    filled_qty,
                    avg_fill_price,
                    approved_by,
                    now,
                    now,
                    UUID(order_id),
                ),
            )
        elif mark_submitted:
            await conn.execute(
                """
                UPDATE theeyebeta.orders
                   SET status = %s,
                       filled_qty = %s,
                       avg_fill_price = %s,
                       submitted_at = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
                (status, filled_qty, avg_fill_price, now, now, UUID(order_id)),
            )
        else:
            await conn.execute(
                """
                UPDATE theeyebeta.orders
                   SET status = %s,
                       filled_qty = %s,
                       avg_fill_price = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
                (status, filled_qty, avg_fill_price, now, UUID(order_id)),
            )
        await conn.commit()
    log.info("order_status_persisted", order_id=order_id, status=status)


async def persist_order_rejection(dsn: str, *, order_id: str, reason: str) -> None:
    """Mark a pending order rejected by the pre-submission risk/compliance gate."""
    now = datetime.now(tz=UTC)
    metadata_patch = json.dumps({"rejection_reason": reason, "rejected_at": now.isoformat()})
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            UPDATE theeyebeta.orders
               SET status = 'rejected',
                   metadata = metadata || %s::jsonb,
                   updated_at = %s
             WHERE id = %s AND status = 'pending_approval'
            """,
            (metadata_patch, now, UUID(order_id)),
        )
        await conn.commit()
    log.info("order_rejected_pre_submission", order_id=order_id, reason=reason)


async def insert_execution(
    dsn: str,
    *,
    order_id: str,
    qty: float,
    price: float,
    commission: float = 0.0,
    raw: dict[str, Any] | None = None,
) -> None:
    """Append one fill to ``executions``."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.executions
                (order_id, ts, qty, price, commission, raw)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                UUID(order_id),
                datetime.now(tz=UTC),
                qty,
                price,
                commission,
                json.dumps(raw or {}),
            ),
        )
        await conn.commit()
    log.info("execution_inserted", order_id=order_id, qty=qty, price=price)


async def fetch_first_portfolio_id(dsn: str) -> str:
    """Return the oldest portfolio id (e2e / smoke helpers)."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            "SELECT id::text FROM theeyebeta.portfolios ORDER BY created_at LIMIT 1",
        )
        row = await cur.fetchone()
    if row is None:
        msg = "no portfolio in database"
        raise ValueError(msg)
    return str(row[0])


async def resolve_instrument_id(dsn: str, symbol: str) -> int:
    """Resolve instrument primary key by ticker symbol."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            "SELECT id FROM theeyebeta.instruments WHERE symbol = %s LIMIT 1",
            (symbol,),
        )
        row = await cur.fetchone()
    if row is None:
        msg = f"instrument {symbol} not found"
        raise ValueError(msg)
    return int(row[0])


async def fetch_local_position_qty(dsn: str, portfolio_id: str, symbol: str) -> float:
    """Return local position qty for one portfolio and symbol."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT p.qty
              FROM theeyebeta.positions p
              JOIN theeyebeta.instruments i ON i.id = p.instrument_id
             WHERE p.portfolio_id = %s AND i.symbol = %s
            """,
            (UUID(portfolio_id), symbol),
        )
        row = await cur.fetchone()
    return float(row[0]) if row else 0.0


async def insert_pending_order(
    dsn: str,
    *,
    portfolio_id: str,
    instrument_id: int,
    side: str,
    qty: float,
    order_id: str | None = None,
) -> str:
    """Insert a pending_approval market order (e2e helper)."""
    oid = UUID(order_id) if order_id else UUID(str(uuid4()))
    client_order_id = f"mo-{oid}"
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.orders
                (id, client_order_id, portfolio_id, instrument_id,
                 side, order_type, qty, status)
            VALUES (%s, %s, %s, %s, %s, 'market', %s, 'pending_approval')
            """,
            (oid, client_order_id, UUID(portfolio_id), instrument_id, side, qty),
        )
        await conn.commit()
    log.info("pending_order_inserted", order_id=str(oid), qty=qty, side=side)
    return str(oid)


async def upsert_position(
    dsn: str,
    *,
    portfolio_id: str,
    instrument_id: int,
    qty_delta: float,
    fill_price: float,
) -> None:
    """Update portfolio position after a fill."""
    now = datetime.now(tz=UTC)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT qty, avg_entry_price
              FROM theeyebeta.positions
             WHERE portfolio_id = %s AND instrument_id = %s
            """,
            (UUID(portfolio_id), instrument_id),
        )
        row = await cur.fetchone()
        if row is None:
            await conn.execute(
                """
                INSERT INTO theeyebeta.positions
                    (portfolio_id, instrument_id, qty, avg_entry_price,
                     market_value, opened_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(portfolio_id),
                    instrument_id,
                    qty_delta,
                    fill_price,
                    abs(qty_delta * fill_price),
                    now,
                    now,
                ),
            )
        else:
            old_qty = float(row[0])
            old_avg = float(row[1])
            new_qty = old_qty + qty_delta
            if abs(new_qty) < 1e-9:
                new_avg = 0.0
            elif qty_delta > 0 and old_qty >= 0:
                new_avg = ((old_qty * old_avg) + (qty_delta * fill_price)) / new_qty
            elif qty_delta > 0 and old_qty < 0:
                new_avg = fill_price if new_qty > 0 else old_avg
            else:
                new_avg = old_avg
            await conn.execute(
                """
                UPDATE theeyebeta.positions
                   SET qty = %s,
                       avg_entry_price = %s,
                       market_value = %s,
                       updated_at = %s
                 WHERE portfolio_id = %s AND instrument_id = %s
                """,
                (
                    new_qty,
                    new_avg,
                    abs(new_qty * fill_price),
                    now,
                    UUID(portfolio_id),
                    instrument_id,
                ),
            )
        await conn.commit()
    log.info(
        "position_updated",
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        qty_delta=qty_delta,
    )
