"""ARGOS sector_context feature block builder."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import asyncpg


def _num(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_sector_context_from_rows(
    rows: list[dict[str, object]],
    as_of_date: date | None,
) -> dict[str, object]:
    """Build the ARGOS sector_context block; never fabricate missing data."""
    if not rows or as_of_date is None:
        return {"data_gaps": ["sector_context"]}

    rotation = [
        {
            "sector": row["sector"],
            "rank": row["rotation_rank"],
            "rel_strength_spx_30d": _num(row["rel_strength_spx_30d"]),
        }
        for row in sorted(
            rows,
            key=lambda r: (r["rotation_rank"] is None, r["rotation_rank"], r["sector"]),
        )
    ]
    breadth = {
        str(row["sector"]): {
            "pct_above_sma_50": _num(row["pct_above_sma_50"]),
            "pct_above_sma_200": _num(row["pct_above_sma_200"]),
        }
        for row in rows
    }
    return {
        "as_of_date": as_of_date.isoformat(),
        "rotation": rotation,
        "breadth": breadth,
        "data_gaps": [],
    }


async def fetch_argos_sector_context(
    conn: asyncpg.Connection,
    *,
    trade_date: date,
    worker_name: str = "ArgosContextWorker",
) -> dict[str, object]:
    """Fetch sector_daily for the last trading day; WARN when absent."""
    last_trading_day = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE calendar_date <= $1
           AND is_trading_day
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )
    expected_date = last_trading_day or trade_date
    rows = await conn.fetch(
        """
        SELECT sector, rotation_rank, rel_strength_spx_30d,
               pct_above_sma_50, pct_above_sma_200
          FROM theeyebeta.sector_daily
         WHERE as_of_date = $1
         ORDER BY rotation_rank NULLS LAST, sector
        """,
        expected_date,
    )
    if not rows:
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_alerts
                (alert_type, severity, trade_date, worker_name, title, message, metadata)
            VALUES ('DATA_GAP', 'WARN', $1, $2, 'Sector context missing', $3, $4::jsonb)
            """,
            expected_date,
            worker_name,
            f"No theeyebeta.sector_daily rows exist for last trading day {expected_date}.",
            json.dumps({"data_gaps": ["sector_context"]}),
        )
        return {"data_gaps": ["sector_context"]}
    return build_sector_context_from_rows([dict(row) for row in rows], expected_date)
