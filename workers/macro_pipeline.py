"""Sequential macro pipeline runner for systemd."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from workers.macro_ingestion_worker import FRED_SERIES, MacroIngestionWorker
from workers.macro_regime_worker import MacroRegimeWorker


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    ingestion = MacroIngestionWorker()
    regime = MacroRegimeWorker()

    ingestion_result = await ingestion.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=len(FRED_SERIES),
    )
    regime_result = await regime.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=1,
    )
    print(
        json.dumps(
            {
                "date": target_date.isoformat(),
                "dry_run": args.dry_run,
                "ingestion": ingestion_result.metadata,
                "regime": regime_result.metadata,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run macro ingestion then macro regime")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; default today")
    parser.add_argument("--run-type", default="manual", choices=["manual", "scheduled", "recovery"])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
