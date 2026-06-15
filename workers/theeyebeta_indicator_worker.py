"""Validate canonical indicator coverage for the active universe."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.calendar import resolve_trading_day_on_or_before

log = structlog.get_logger()


async def resolve_target_trade_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest trading day on or before ``as_of``."""
    return await resolve_trading_day_on_or_before(conn, as_of)


class TheeyebetaIndicatorWorker(BaseWorker):
    """Validate same-day indicator rows exist in theeyebeta.ind_technical_daily."""

    worker_name = "TheeyebetaIndicatorWorker"
    worker_type = "indicators"
    display_name = "Theeyebeta Indicator Validation"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)
        active = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                  FROM theeyebeta.instruments i
                  JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
                 WHERE i.active
                """,
            )
            or 0,
        )
        priced = int(
            await conn.fetchval(
                """
                SELECT COUNT(DISTINCT p.instrument_id)
                  FROM theeyebeta.prices_daily p
                  JOIN theeyebeta.instruments i ON i.id = p.instrument_id AND i.active
                 WHERE p.ts::date = $1
                """,
                target,
            )
            or 0,
        )
        indicator_rows = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                  FROM theeyebeta.ind_technical_daily d
                  JOIN theeyebeta.instruments i ON i.id = d.instrument_id AND i.active
                 WHERE d.date = $1
                """,
                target,
            )
            or 0,
        )
        coverage = indicator_rows / priced if priced else 0.0
        metadata: dict[str, Any] = {
            "trade_date": target.isoformat(),
            "active_universe": active,
            "priced_today": priced,
            "indicator_rows": indicator_rows,
            "coverage": round(coverage, 4),
            "dry_run": dry_run,
            "source": "theeyebeta.ind_technical_daily validation",
        }
        if priced and indicator_rows == 0:
            msg = (
                f"Precondition failed: theeyebeta.ind_technical_daily has no "
                f"rows for {target.isoformat()}"
            )
            raise RuntimeError(msg)
        log.info("indicator_validation_complete", **metadata)
        return WorkerResult(
            records_written=0,
            records_expected=priced,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = TheeyebetaIndicatorWorker()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Canonical indicator validation")
    parser.add_argument("--date", help="Anchor trade date YYYY-MM-DD")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
