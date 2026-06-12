"""Scheduled daily pipeline runner with trading-calendar gate and audit lifecycle.

Invokes the legacy ``core.pipeline.daily_pipeline`` entrypoint from TheEyeBetaLocal
while writing terminal ``audit_worker_runs`` rows under ``worker_name=daily_pipeline``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import asyncpg

from workers.base_worker import BaseWorker, WorkerResult

_LOCAL_ROOT = Path(__file__).resolve().parents[1].parent / "TheEyeBetaLocal"


def _ensure_local_paths() -> None:
    """Add TheEyeBetaLocal packages to ``sys.path`` for pipeline imports."""
    paths = [
        _LOCAL_ROOT / "packages" / "core" / "src",
        _LOCAL_ROOT / "packages" / "data_access" / "src",
        _LOCAL_ROOT / "packages" / "providers" / "src",
        _LOCAL_ROOT / "services" / "etl" / "src",
    ]
    for path in paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


class DailyPipelineRunner(BaseWorker):
    """Run the legacy daily pipeline once with a terminal audit row."""

    worker_name = "daily_pipeline"
    worker_type = "daily_pipeline"
    display_name = "Daily Pipeline"

    async def _is_trading_day(self, conn: asyncpg.Connection, trade_date: date) -> bool:
        value = await conn.fetchval(
            """
            SELECT is_trading_day
              FROM public.trading_calendar
             WHERE calendar_date = $1
             LIMIT 1
            """,
            trade_date,
        )
        if value is None:
            return trade_date.weekday() < 5
        return bool(value)

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        if not await self._is_trading_day(conn, trade_date):
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={"skipped": True, "reason": "non_trading_day"},
            )

        if dry_run:
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={"dry_run": True, "would_run": "core.pipeline.daily_pipeline"},
            )

        summary = await asyncio.to_thread(_run_legacy_pipeline, trade_date)
        exit_code = int(summary.exit_code)
        metadata = json.loads(summary.to_json())
        records_written = int(summary.successful_tickers or 0)
        records_expected = int(summary.total_tickers or 0)

        if exit_code not in {0, 1, 2}:
            msg = f"daily_pipeline exit_code={exit_code} status={summary.status}"
            raise RuntimeError(msg)

        return WorkerResult(
            records_written=records_written,
            records_expected=records_expected,
            metadata=metadata,
        )


def _run_legacy_pipeline(trade_date: date) -> object:
    """Execute the legacy pipeline synchronously on a worker thread."""
    _ensure_local_paths()
    from core.pipeline.daily_pipeline import run_daily_pipeline

    return run_daily_pipeline(
        mode="full",
        target_date=trade_date,
        skip_if_not_trading_day=True,
        force_update=True,
        post_close_delay_hours=0.0,
    )


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    worker = DailyPipelineRunner()
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the audited daily pipeline")
    parser.add_argument("--date", help="Target trade date YYYY-MM-DD; default today")
    parser.add_argument(
        "--run-type",
        default="scheduled",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
