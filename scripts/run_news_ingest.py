#!/usr/bin/env python
"""Run news RSS ingest + sync to market_news (DataAPI source table)."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import structlog
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

log = structlog.get_logger()
REPO = Path(__file__).resolve().parents[1]
LOOKBACK_DAYS = int(os.environ.get("NEWS_LOOKBACK_DAYS", "3"))


async def _ingest_day(target: date) -> dict:
    from data_ingestion.pipeline import run_adapter  # noqa: PLC0415

    return await run_adapter("news", target)


async def _main() -> None:
    today = date.today()
    total_written = 0
    for offset in range(LOOKBACK_DAYS):
        target = today - timedelta(days=offset)
        result = await _ingest_day(target)
        written = result.get("written", {})
        if isinstance(written, dict):
            total_written += int(written.get("news_articles", 0))
        log.info("news_ingest_day", date=str(target), **result)

    sync = await asyncio.create_subprocess_exec(
        sys.executable,
        str(REPO / "scripts" / "sync_market_news.py"),
        cwd=REPO,
    )
    returncode = await sync.wait()
    if returncode != 0:
        raise SystemExit(returncode)
    log.info("news_pipeline_complete", days=LOOKBACK_DAYS, articles_written=total_written)


if __name__ == "__main__":
    asyncio.run(_main())
