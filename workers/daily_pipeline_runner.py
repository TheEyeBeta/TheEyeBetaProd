"""Scheduled daily pipeline runner with trading-calendar gate and audit lifecycle.

Orchestrates native indicator compute (``IndicatorComputeWorker``) writing directly
to ``theeyebeta.ind_technical_daily``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

import asyncpg

from workers.base_worker import BaseWorker, WorkerResult
from workers.calendar import is_trading_day
from workers.indicator_compute_worker import IndicatorComputeWorker


class DailyPipelineRunner(BaseWorker):
    """Run the canonical daily indicator pipeline once with a terminal audit row."""

    worker_name = "daily_pipeline"
    worker_type = "daily_pipeline"
    display_name = "Daily Pipeline"

    def __init__(self, *, database_url: str | None = None) -> None:
        super().__init__(database_url=database_url)

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        if not await is_trading_day(conn, trade_date):
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={"skipped": True, "reason": "non_trading_day"},
            )

        if dry_run:
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={
                    "dry_run": True,
                    "would_run": "workers.indicator_compute_worker",
                    "trade_date": trade_date.isoformat(),
                },
            )

        compute = IndicatorComputeWorker(database_url=self.database_url)
        result = await compute.execute(conn, trade_date, dry_run=False)
        metadata = {
            "engine": "indicator_compute",
            "trade_date": trade_date.isoformat(),
            **result.metadata,
        }
        return WorkerResult(
            records_written=result.records_written,
            records_expected=result.records_expected,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = DailyPipelineRunner()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Run the audited daily pipeline")
    parser.add_argument("--date", help="Trade date YYYY-MM-DD")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--engine",
        default="indicator_compute",
        help="Deprecated; kept for systemd compatibility",
    )
    parser.add_argument("--mode", default="full", help="Deprecated compatibility flag")
    parser.add_argument("--force-update", action="store_true", help="Deprecated compatibility flag")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
