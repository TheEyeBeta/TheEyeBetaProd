"""Live-trading approval gate (architecture Part 8.3)."""

from __future__ import annotations

import psycopg
import structlog

log = structlog.get_logger()


class LiveTradingNotApprovedError(RuntimeError):
    """Raised when live mode is requested without DB approval."""


async def assert_live_trading_allowed(dsn: str) -> None:
    """Require ``accounts.metadata.live_approval`` before live trading.

    Args:
        dsn: Postgres connection string.

    Raises:
        LiveTradingNotApprovedError: When no live account has approval metadata.
    """
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
