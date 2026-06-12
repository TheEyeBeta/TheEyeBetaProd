"""Native canonical indicator worker — reads theeyebeta.prices_daily only.

Phase C: full column parity vs legacy compute_technical_daily.py pending
validation against Massive indicator endpoints. Writes theeyebeta.ind_technical_daily.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult

log = structlog.get_logger()

CHUNK_SIZE = 100


class TheeyebetaIndicatorWorker(BaseWorker):
    """Compute technical indicators from canonical daily bars."""

    worker_name = "TheeyebetaIndicatorWorker"
    worker_type = "indicators"
    display_name = "Canonical Indicator Worker"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        """Placeholder execute — implement vectorized kernel after C1 validation."""
        count = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT instrument_id)
              FROM theeyebeta.prices_daily
             WHERE ts::date = $1
            """,
            trade_date,
        )
        metadata = {
            "trade_date": trade_date.isoformat(),
            "instruments_with_prices": int(count or 0),
            "dry_run": dry_run,
            "status": "skeleton — wire compute kernel in Phase C validation pass",
        }
        if dry_run:
            return WorkerResult(records_written=0, records_expected=int(count or 0), metadata=metadata)
        return WorkerResult(records_written=0, records_expected=int(count or 0), metadata=metadata)


async def _async_main(args: argparse.Namespace) -> None:
    worker = TheeyebetaIndicatorWorker()
    target = date.fromisoformat(args.date) if args.date else date.today()
    result = await worker.run(target, run_type="manual", dry_run=args.dry_run)
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical indicator worker (Phase C)")
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
