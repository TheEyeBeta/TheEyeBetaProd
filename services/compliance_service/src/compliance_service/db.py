"""Compliance persistence and context loading."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import structlog

from compliance_service.models import (
    ComplianceMandate,
    ComplianceOutcome,
    PortfolioContext,
    RecentOrder,
    RuleResult,
)

log = structlog.get_logger()


async def load_check_context(
    dsn: str,
    *,
    portfolio_id: str,
    instrument_id: int,
    order_id: str | None = None,
) -> tuple[PortfolioContext, ComplianceMandate, str]:
    """Load portfolio, mandate, instrument metadata, and recent orders."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT p.id, p.account_id, a.broker, a.mode, a.base_currency, p.mandate
              FROM theeyebeta.portfolios p
              JOIN theeyebeta.accounts a ON a.id = p.account_id
             WHERE p.id = %s
            """,
            (UUID(portfolio_id),),
        )
        row = await cur.fetchone()
        if row is None:
            msg = f"portfolio {portfolio_id} not found"
            raise ValueError(msg)

        mandate_raw = row[5] or {}
        if isinstance(mandate_raw, str):
            mandate_raw = json.loads(mandate_raw)
        compliance_raw = mandate_raw.get("compliance") or mandate_raw
        mandate = ComplianceMandate.model_validate(compliance_raw)

        cur = await conn.execute(
            """
            SELECT symbol, metadata
              FROM theeyebeta.instruments
             WHERE id = %s
            """,
            (instrument_id,),
        )
        inst = await cur.fetchone()
        if inst is None:
            msg = f"instrument {instrument_id} not found"
            raise ValueError(msg)
        symbol = str(inst[0])
        metadata = inst[1] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        cur = await conn.execute(
            """
            SELECT COALESCE(SUM(market_value), 0)
              FROM theeyebeta.positions
             WHERE portfolio_id = %s
            """,
            (UUID(portfolio_id),),
        )
        equity = float((await cur.fetchone())[0] or 0.0)
        if equity <= 0:
            equity = 1_000_000.0

        since = datetime.now(tz=UTC) - timedelta(days=35)
        cur = await conn.execute(
            """
            SELECT instrument_id, side, qty, limit_price, created_at
              FROM theeyebeta.orders
             WHERE portfolio_id = %s
               AND created_at >= %s
             ORDER BY created_at DESC
            """,
            (UUID(portfolio_id), since),
        )
        order_rows = await cur.fetchall()

        day_trades = _count_day_trades(order_rows)

    recent = [
        RecentOrder(
            instrument_id=int(r[0]),
            side=str(r[1]),
            qty=float(r[2]),
            limit_price=float(r[3]) if r[3] is not None else None,
            created_at=r[4],
            realized_pnl=_synthetic_realized_pnl(str(r[1]), float(r[3] or 0)),
        )
        for r in order_rows
    ]

    portfolio = PortfolioContext(
        portfolio_id=portfolio_id,
        account_id=str(row[1]),
        broker=str(row[2]),
        account_mode=str(row[3]),
        base_currency=str(row[4]),
        equity_usd=equity,
        day_trades_5d=day_trades,
        recent_orders=recent,
        instrument_metadata=dict(metadata),
    )
    return portfolio, mandate, symbol


def _synthetic_realized_pnl(side: str, price: float) -> float | None:
    """Approximate P&L sign for wash-sale tests when fills are unavailable."""
    if side.lower() != "sell":
        return None
    return -abs(price) * 0.01


def _count_day_trades(order_rows: list[tuple[Any, ...]]) -> int:
    """Count instruments with both buy and sell activity in the last 5 sessions."""
    days_5 = datetime.now(tz=UTC).date() - timedelta(days=5)
    by_inst: dict[int, set[str]] = {}
    for row in order_rows:
        created = row[4]
        if created.date() < days_5:
            continue
        inst = int(row[0])
        side = str(row[1]).lower()
        by_inst.setdefault(inst, set()).add(side)
    return sum(1 for sides in by_inst.values() if "buy" in sides and "sell" in sides)


async def load_active_holds_and_overrides(
    dsn: str,
    *,
    portfolio_id: str,
    account_id: str,
    symbol: str,
    instrument_id: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load active legal holds and non-expired compliance overrides for this order."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT entity_type, entity_id, reason, placed_by, placed_at
              FROM theeyebeta.admin_legal_holds
             WHERE active
               AND (
                     (entity_type = 'portfolio' AND entity_id = %s)
                  OR (entity_type = 'account' AND entity_id = %s)
                  OR (entity_type = 'instrument' AND entity_id IN (%s, %s))
                   )
            """,
            (portfolio_id, account_id, symbol, str(instrument_id)),
        )
        hold_rows = await cur.fetchall()

        cur = await conn.execute(
            """
            SELECT portfolio_id, rule_id, reason, actor, expires_at
              FROM theeyebeta.admin_compliance_overrides
             WHERE active
               AND (expires_at IS NULL OR expires_at > now())
               AND (portfolio_id IS NULL OR portfolio_id = %s)
             ORDER BY portfolio_id NULLS FIRST
            """,
            (UUID(portfolio_id),),
        )
        override_rows = await cur.fetchall()

    holds = [
        {
            "entity_type": str(r[0]),
            "entity_id": str(r[1]),
            "reason": str(r[2]),
            "placed_by": str(r[3]),
            "placed_at": r[4],
        }
        for r in hold_rows
    ]
    # Portfolio-scoped overrides are ordered last so they win over a global
    # (portfolio_id IS NULL) override for the same rule_id.
    overrides_by_rule: dict[str, dict[str, Any]] = {}
    for r in override_rows:
        overrides_by_rule[str(r[1])] = {
            "portfolio_id": str(r[0]) if r[0] else None,
            "rule_id": str(r[1]),
            "reason": str(r[2]),
            "actor": str(r[3]),
            "expires_at": r[4],
        }
    return holds, overrides_by_rule


async def persist_compliance_checks(
    dsn: str,
    *,
    portfolio_id: str,
    order_id: str | None,
    results: list[RuleResult],
) -> None:
    """Insert one ``compliance_checks`` row per rule outcome."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        for result in results:
            await conn.execute(
                """
                INSERT INTO theeyebeta.compliance_checks
                    (order_id, portfolio_id, rule_id, outcome, detail, checked_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(order_id) if order_id else None,
                    UUID(portfolio_id),
                    result.rule_id,
                    result.outcome.db_value(),
                    result.detail,
                    datetime.now(tz=UTC),
                ),
            )
        await conn.commit()
    log.info(
        "compliance_checks_inserted",
        portfolio_id=portfolio_id,
        order_id=order_id,
        count=len(results),
    )


async def reject_order_if_blocked(
    dsn: str,
    *,
    order_id: str | None,
    outcome: ComplianceOutcome,
    rule_id: str | None,
) -> None:
    """Move an order to ``rejected`` when a rule blocks."""
    if order_id is None or outcome != ComplianceOutcome.BLOCK or rule_id is None:
        return
    detail = f"rejected by compliance rule {rule_id}"
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            UPDATE theeyebeta.orders
               SET status = 'rejected',
                   updated_at = now()
             WHERE id = %s
            """,
            (UUID(order_id),),
        )
        await conn.commit()
    log.info("order_rejected_compliance", order_id=order_id, rule_id=rule_id, detail=detail)
