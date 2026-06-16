"""Live-trading approval gate and data-quality submission blocks."""

from __future__ import annotations

import os

import psycopg
import structlog

log = structlog.get_logger()

REDIS_LIVE_ENABLED_KEY = "trading:live_enabled"


class LiveTradingNotApprovedError(RuntimeError):
    """Raised when live mode is requested without DB approval."""


class DataGapBlockError(RuntimeError):
    """Raised when unacknowledged CRITICAL data gaps block submission."""

    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        super().__init__(
            f"order submission blocked: unacknowledged_data_gaps ({len(symbols)} alerts)",
        )


class TradingDisabledError(RuntimeError):
    """Raised when Redis live-trading flag is off."""


async def assert_live_trading_allowed(dsn: str) -> None:
    """Require ``accounts.metadata.live_approval`` before live trading."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT external_id
              FROM theeyebeta.accounts
             WHERE mode = 'live'
               AND COALESCE((metadata->>'live_approval')::boolean, false) = true
             LIMIT 1
            """,
        )
        row = await cur.fetchone()
    if row is None:
        msg = (
            "live trading blocked: no theeyebeta.accounts row with "
            "metadata.live_approval=true (Part 8.3)"
        )
        log.error("live_trading_gate_failed")
        raise LiveTradingNotApprovedError(msg)
    log.info("live_trading_gate_passed", account_external_id=str(row[0]))


async def assert_redis_live_enabled(redis_url: str) -> None:
    """Require Redis ``trading:live_enabled=true`` for live submissions."""
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        msg = "redis package required for live trading gate"
        raise TradingDisabledError(msg) from exc

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        enabled = await client.get(REDIS_LIVE_ENABLED_KEY)
    finally:
        await client.aclose()
    if enabled != "true":
        raise TradingDisabledError("trading:live_enabled is not true in Redis")


async def fetch_critical_gap_block_symbols(dsn: str) -> list[str]:
    """Return symbols/labels for unacknowledged CRITICAL gap alerts."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT DISTINCT COALESCE(message, title) AS label
              FROM theeyebeta.audit_alerts
             WHERE severity = 'CRITICAL'
               AND acknowledged_at IS NULL
               AND resolved_at IS NULL
               AND (title ILIKE '%gap%' OR worker_name ILIKE '%sentinel%')
             ORDER BY 1
             LIMIT 100
            """,
        )
        rows = await cur.fetchall()
    return [str(row[0]) for row in rows if row[0]]


async def assert_no_data_gap_block(dsn: str) -> None:
    """Block submission when CRITICAL gap alerts are unacknowledged."""
    symbols = await fetch_critical_gap_block_symbols(dsn)
    if symbols:
        log.warning("data_gap_block_active", count=len(symbols))
        raise DataGapBlockError(symbols)


async def assert_order_submission_allowed(
    dsn: str,
    *,
    live_mode: bool = False,
    redis_url: str | None = None,
) -> None:
    """Combined gate: data gaps + optional live approval checks."""
    await assert_no_data_gap_block(dsn)
    if live_mode:
        await assert_live_trading_allowed(dsn)
        url = redis_url or os.environ.get("REDIS_OPS_URL", os.environ.get("REDIS_URL", ""))
        if url:
            await assert_redis_live_enabled(url)
