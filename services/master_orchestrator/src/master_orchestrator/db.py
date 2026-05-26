"""Persist proposed orders and publish NATS events."""

from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import nats
import psycopg
import structlog

from master_orchestrator.models import TradeTicket

log = structlog.get_logger()


async def resolve_portfolio_id(explicit: str, dsn: str) -> UUID:
    """Return configured portfolio or the first portfolio in the database."""
    if explicit:
        return UUID(explicit)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute("SELECT id FROM theeyebeta.portfolios ORDER BY created_at LIMIT 1")
        row = await cur.fetchone()
    if row is None:
        msg = "No portfolio found; set DEFAULT_PORTFOLIO_ID"
        raise OSError(msg)
    return row[0]


async def insert_pending_order(
    *,
    dsn: str,
    portfolio_id: UUID,
    ticket: TradeTicket,
) -> UUID:
    """Insert one order row with status pending_approval."""
    order_id = uuid4()
    client_order_id = f"mo-{order_id}"
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.orders
                (id, client_order_id, portfolio_id, instrument_id, decision_id,
                 side, order_type, qty, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'market', %s, 'pending_approval')
            """,
            (
                order_id,
                client_order_id,
                portfolio_id,
                ticket.instrument_id,
                ticket.decision_id,
                ticket.side,
                ticket.qty,
            ),
        )
        await conn.commit()
    log.info(
        "order_proposed",
        order_id=str(order_id),
        instrument_id=ticket.instrument_id,
        side=ticket.side,
        qty=ticket.qty,
    )
    return order_id


async def publish_order_proposed(order_id: UUID, ticket: TradeTicket) -> None:
    """Publish ``orders.proposed.{order_id}`` on NATS."""
    nats_url = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
    subject = f"orders.proposed.{order_id}"
    payload = json.dumps(
        {
            "order_id": str(order_id),
            "market": ticket.market,
            "instrument_id": ticket.instrument_id,
            "side": ticket.side,
            "qty": ticket.qty,
            "horizon_days": ticket.horizon_days,
            "rationale_summary": ticket.rationale_summary,
            "status": "pending_approval",
        },
    ).encode()
    nc = await nats.connect(nats_url)
    try:
        await nc.publish(subject, payload)
        log.info("order_proposed_published", subject=subject)
    finally:
        await nc.close()
