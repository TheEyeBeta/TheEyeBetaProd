"""Platform status queries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg


async def fetch_platform_summary(conn: asyncpg.Connection) -> dict[str, Any]:
    """Universe counts, price freshness, stale heartbeats."""
    active = await conn.fetchval(
        "SELECT COUNT(*) FROM theeyebeta.instruments WHERE active"
    )
    intraday = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT i.id)
          FROM theeyebeta.instruments i
          JOIN theeyebeta.market_cap_daily c
            ON c.symbol = i.symbol AND c.as_of_date = (
                SELECT MAX(as_of_date) FROM theeyebeta.market_cap_daily
            )
         WHERE i.active AND c.market_cap >= 500000000
        """,
    )
    latest_daily = await conn.fetchval(
        "SELECT MAX(ts::date) FROM theeyebeta.prices_daily"
    )
    latest_intraday = await conn.fetchval(
        "SELECT MAX(ts) FROM theeyebeta.prices_intraday"
    )
    stale_workers = await conn.fetch(
        """
        SELECT worker_id, last_heartbeat
          FROM theeyebeta.worker_heartbeats
         WHERE last_heartbeat < $1
         ORDER BY worker_id
        """,
        datetime.now(UTC) - timedelta(hours=26),
    )
    return {
        "active_eod_universe": int(active or 0),
        "intraday_eligible": int(intraday or 0),
        "latest_daily_date": str(latest_daily) if latest_daily else None,
        "latest_intraday_ts": latest_intraday.isoformat() if latest_intraday else None,
        "stale_heartbeats": [
            {"worker_id": r["worker_id"], "last": r["last_heartbeat"].isoformat()}
            for r in stale_workers
        ],
    }


async def fetch_canonical_status(conn: asyncpg.Connection) -> dict[str, Any]:
    """Prices and indicators freshness for the latest trading day."""
    latest_daily = await conn.fetchval(
        "SELECT MAX(ts::date) FROM theeyebeta.prices_daily"
    )
    active = int(
        await conn.fetchval("SELECT COUNT(*) FROM theeyebeta.instruments WHERE active")
        or 0
    )
    price_rows = 0
    ind_rows = 0
    if latest_daily:
        price_rows = int(
            await conn.fetchval(
                """
                SELECT COUNT(DISTINCT instrument_id)
                  FROM theeyebeta.prices_daily
                 WHERE ts::date = $1
                """,
                latest_daily,
            )
            or 0,
        )
        ind_rows = 0
        try:
            ind_rows = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM theeyebeta.ind_technical_daily WHERE date = $1",
                    latest_daily,
                )
                or 0,
            )
        except asyncpg.InsufficientPrivilegeError:
            ind_rows = -1
    return {
        "latest_daily_date": str(latest_daily) if latest_daily else None,
        "active_universe": active,
        "price_instruments": price_rows,
        "indicator_rows": ind_rows,
        "price_coverage_pct": round(100.0 * price_rows / active, 2) if active else 0.0,
        "indicator_coverage_pct": (
            round(100.0 * ind_rows / active, 2) if active and ind_rows >= 0 else None
        ),
    }


async def fetch_intraday_coverage(
    conn: asyncpg.Connection,
    *,
    bucket_date: date | None = None,
) -> dict[str, Any]:
    """Intraday bucket fill rate vs eligible universe."""
    eligible = int(
        await conn.fetchval(
            """
            SELECT COUNT(DISTINCT i.id)
              FROM theeyebeta.instruments i
              JOIN theeyebeta.market_cap_daily c
                ON c.symbol = i.symbol AND c.as_of_date = (
                    SELECT MAX(as_of_date) FROM theeyebeta.market_cap_daily
                )
             WHERE i.active AND c.market_cap >= 500000000
            """,
        )
        or 0,
    )
    if bucket_date is None:
        latest = await conn.fetchval("SELECT MAX(ts) FROM theeyebeta.prices_intraday")
        bucket_date = latest.date() if latest else date.today()
    rows = await conn.fetch(
        """
        SELECT ts, COUNT(DISTINCT instrument_id) AS cnt
          FROM theeyebeta.prices_intraday
         WHERE ts::date = $1
         GROUP BY ts
         ORDER BY ts DESC
         LIMIT 1
        """,
        bucket_date,
    )
    if rows:
        bucket_ts = rows[0]["ts"]
        filled = int(rows[0]["cnt"])
    else:
        bucket_ts = None
        filled = 0
    pct = round(100.0 * filled / eligible, 2) if eligible else 0.0
    return {
        "bucket_date": bucket_date.isoformat(),
        "bucket_ts": bucket_ts.isoformat() if bucket_ts else None,
        "eligible": eligible,
        "filled": filled,
        "coverage_pct": pct,
    }
