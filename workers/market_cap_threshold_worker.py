"""Detect market-cap threshold crossings and record audit events."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.market_cap_providers import (
    CAP_THRESHOLD_USD,
    CapSnapshot,
    action_for_event,
    classify_cap_crossings,
)

log = structlog.get_logger()


async def resolve_target_trade_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest trading day on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date <= $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        as_of,
    )
    if value is None:
        msg = f"No trading day found on or before {as_of.isoformat()}"
        raise RuntimeError(msg)
    return value


async def prior_trading_day(conn: asyncpg.Connection, trade_date: date) -> date | None:
    """Return the previous trading day before ``trade_date``."""
    return await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )


async def load_cap_snapshot_map(
    conn: asyncpg.Connection,
    as_of_date: date,
) -> dict[str, CapSnapshot]:
    """Load symbol → cap snapshot for one trade date."""
    rows = await conn.fetch(
        """
        SELECT symbol, market_cap, instrument_id
          FROM theeyebeta.market_cap_daily
         WHERE as_of_date = $1
        """,
        as_of_date,
    )
    return {
        str(row["symbol"]).upper(): CapSnapshot(
            symbol=str(row["symbol"]).upper(),
            market_cap=float(row["market_cap"]),
            instrument_id=int(row["instrument_id"]) if row["instrument_id"] is not None else None,
        )
        for row in rows
    }


async def record_cap_events(
    conn: asyncpg.Connection,
    trade_date: date,
    crossings: list[Any],
) -> int:
    """Insert crossing events that are not already recorded for ``trade_date``."""
    written = 0
    for crossing in crossings:
        exists = await conn.fetchval(
            """
            SELECT 1
              FROM theeyebeta.audit_cap_events
             WHERE trade_date = $1
               AND symbol = $2
               AND event_type = $3
             LIMIT 1
            """,
            trade_date,
            crossing.symbol,
            crossing.event_type,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_cap_events (
                trade_date, symbol, instrument_id, event_type,
                market_cap, prior_market_cap, action_required
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            trade_date,
            crossing.symbol,
            crossing.instrument_id,
            crossing.event_type,
            Decimal(str(crossing.market_cap)),
            Decimal(str(crossing.prior_market_cap))
            if crossing.prior_market_cap is not None
            else None,
            action_for_event(crossing.event_type),
        )
        written += 1
    return written


class MarketCapThresholdWorker(BaseWorker):
    """Detect $500M market-cap crossings between consecutive snapshots."""

    worker_name = "MarketCapThresholdWorker"
    worker_type = "market_cap"
    display_name = "Market Cap Threshold"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)
        previous = await prior_trading_day(conn, target)
        if previous is None:
            return WorkerResult(
                records_written=0,
                metadata={"skipped": True, "reason": "no prior trading day"},
            )

        today_map = await load_cap_snapshot_map(conn, target)
        prior_map = await load_cap_snapshot_map(conn, previous)
        if not today_map:
            msg = (
                f"No market_cap_daily rows for {target.isoformat()}; run MarketCapFetchWorker first"
            )
            raise RuntimeError(msg)

        crossings = classify_cap_crossings(today_map, prior_map, threshold=CAP_THRESHOLD_USD)
        up_symbols = [row.symbol for row in crossings if row.event_type == "CROSSED_UP"]
        down_symbols = [row.symbol for row in crossings if row.event_type == "CROSSED_DOWN"]

        metadata: dict[str, Any] = {
            "trade_date": target.isoformat(),
            "prior_date": previous.isoformat(),
            "crossed_up": len(up_symbols),
            "crossed_down": len(down_symbols),
            "symbols_up": up_symbols[:50],
            "symbols_down": down_symbols[:50],
            "threshold_usd": CAP_THRESHOLD_USD,
            "dry_run": dry_run,
        }

        if dry_run:
            return WorkerResult(
                records_written=0,
                records_expected=len(crossings),
                metadata=metadata,
            )

        written = await record_cap_events(conn, target, crossings)
        if crossings:
            log.warning(
                "market_cap_threshold_crossings",
                crossed_up=len(up_symbols),
                crossed_down=len(down_symbols),
            )
        metadata["events_recorded"] = written
        return WorkerResult(
            records_written=written,
            records_expected=len(crossings),
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = MarketCapThresholdWorker()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    """CLI entrypoint for the market-cap threshold worker."""
    parser = argparse.ArgumentParser(description="Detect market-cap threshold crossings")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD; default today")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
