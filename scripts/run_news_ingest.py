#!/usr/bin/env python
"""Run the news RSS ingestion adapter once (driver for the theeye-news-ingest timer).

Invokes ``data_ingestion.pipeline.run_adapter("news", today)`` which fetches the
configured RSS feeds and writes URL-SHA256-deduplicated rows into
``theeyebeta.news_articles`` (ON CONFLICT DO NOTHING, so reruns are cheap).

Why a standalone driver instead of the data_ingestion FastAPI service: that service
is scaffolded and intentionally not deployed (see SERVICES_STATUS.md). This timer runs
only the news adapter so the news layer stays fresh without standing up the whole
service. Prices/macro are already covered by their own ingestors.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date

import structlog
from dotenv import load_dotenv

load_dotenv()
# otel-collector is not running on this host; avoid console-exporter span spam in journal.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

log = structlog.get_logger()


async def _main() -> None:
    from data_ingestion.pipeline import run_adapter  # noqa: PLC0415

    result = await run_adapter("news", date.today())
    log.info("news_ingest_complete", **result)


if __name__ == "__main__":
    asyncio.run(_main())
