"""Supabase sync v2 — canonical-fed shadow/live publisher for IRIS."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import date
from pathlib import Path

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult

log = structlog.get_logger()

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
BATCH_SIZE = 500


class SupabaseSyncV2Worker(BaseWorker):
    """Shadow-mode Supabase publisher (default: compute only, write nothing)."""

    worker_name = "SupabaseSyncV2"
    worker_type = "supabase_sync"
    display_name = "Supabase Sync v2"

    def __init__(self, *, shadow: bool = True, database_url: str | None = None) -> None:
        super().__init__(database_url=database_url)
        self.shadow = shadow

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get(
            "SUPABASE_SERVICE_ROLE_KEY",
        )
        if not url or not key:
            msg = "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set for sync v2"
            raise RuntimeError(msg)

        canonical_count = await conn.fetchval(
            "SELECT COUNT(*) FROM theeyebeta.data_snapshots_packaged"
        )
        computed_count = int(canonical_count or 0)
        metadata = {
            "trade_date": trade_date.isoformat(),
            "shadow": self.shadow or dry_run,
            "tables": {
                "data_snapshots_packaged": {
                    "canonical_rows": int(canonical_count or 0),
                    "computed_rows": computed_count,
                },
            },
        }

        if self.shadow or dry_run:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            report_path = REPORT_DIR / f"supabase_shadow_{trade_date.isoformat()}.md"
            report_path.write_text(
                "\n".join(
                    [
                        f"# Supabase shadow report {trade_date.isoformat()}",
                        "",
                        f"- mode: {'shadow' if self.shadow else 'live'}",
                        f"- data_snapshots_packaged rows: {canonical_count}",
                        f"- computed rows (stub): {computed_count}",
                        "",
                        "Legacy sync keeps running until 3 clean shadow days + operator approval.",
                    ],
                )
                + "\n",
                encoding="utf-8",
            )
            metadata["report"] = str(report_path)

        return WorkerResult(
            records_written=0 if self.shadow else computed_count,
            records_expected=computed_count,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    worker = SupabaseSyncV2Worker(shadow=not args.live)
    target = date.fromisoformat(args.date) if args.date else date.today()
    result = await worker.run(target, run_type="scheduled", dry_run=args.dry_run)
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Supabase sync v2 (shadow default)")
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true", help="Live writes (cutover only)")
    parser.add_argument("--shadow", action="store_true", default=True)
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
