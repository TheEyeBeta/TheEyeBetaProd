#!/usr/bin/env python
"""Sync all news sources into theeyebeta.market_news for DataAPI routes."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta

import structlog
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

log = structlog.get_logger()

LOOKBACK_HOURS = int(os.environ.get("NEWS_BRIDGE_LOOKBACK_HOURS", "168"))
BATCH_LIMIT = int(os.environ.get("NEWS_BRIDGE_BATCH_LIMIT", "1000"))


def _dsn() -> str:
    raw = (
        os.environ.get("NEWS_BRIDGE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("INGEST_DATABASE_URL")
        or ""
    )
    if not raw:
        raise SystemExit("Set DATABASE_URL or INGEST_DATABASE_URL")
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw.split(prefix, 1)[1]
    return raw


def _content_hash(headline: str, url: str) -> str:
    return hashlib.sha256(f"{headline}|{url}".encode()).hexdigest()


async def _upsert_market_news(
    conn,
    *,
    provider: str,
    url: str,
    headline: str,
    summary: str | None,
    source: str | None,
    category: str | None,
    published_at: datetime,
    related: str | None = None,
) -> bool:
    content_hash = _content_hash(headline, url)
    result = await conn.execute(
        """
        INSERT INTO theeyebeta.market_news (
            provider, url, headline, summary, source, category, related,
            published_at, content_hash
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9
        )
        ON CONFLICT (provider, url) DO UPDATE SET
            headline = EXCLUDED.headline,
            summary = EXCLUDED.summary,
            source = EXCLUDED.source,
            category = EXCLUDED.category,
            related = EXCLUDED.related,
            published_at = EXCLUDED.published_at,
            fetched_at = now()
        """,
        provider,
        url,
        headline,
        summary,
        source,
        category,
        related,
        published_at,
        content_hash,
    )
    return result.endswith("1")


async def _main() -> None:
    import asyncpg  # noqa: PLC0415

    cutoff = datetime.now(UTC) - timedelta(hours=LOOKBACK_HOURS)
    conn = await asyncpg.connect(_dsn())
    upserts = 0
    try:
        # Prod RSS path
        rss_rows = await conn.fetch(
            """
            SELECT published_at, source, headline, body, url,
                   array_to_string(tickers, ',') AS tickers
              FROM theeyebeta.news_articles
             WHERE published_at >= $1
             ORDER BY published_at DESC
             LIMIT $2
            """,
            cutoff,
            BATCH_LIMIT,
        )
        for row in rss_rows:
            url = row["url"] or f"news-articles://{row['headline'][:40]}"
            if await _upsert_market_news(
                conn,
                provider="prod-rss",
                url=url,
                headline=row["headline"],
                summary=(row["body"] or "")[:2000] or None,
                source=row["source"],
                category="general",
                published_at=row["published_at"],
                related=row["tickers"] or None,
            ):
                upserts += 1

        # Local engine path (public.market_news)
        engine_exists = await conn.fetchval(
            """
            SELECT to_regclass('public.market_news') IS NOT NULL
            """,
        )
        if engine_exists:
            engine_rows = await conn.fetch(
                """
                SELECT provider, url, headline, summary, source, category, related,
                       published_at
                  FROM public.market_news
                 WHERE published_at >= $1
                 ORDER BY published_at DESC
                 LIMIT $2
                """,
                cutoff,
                BATCH_LIMIT,
            )
            for row in engine_rows:
                if await _upsert_market_news(
                    conn,
                    provider=str(row["provider"]),
                    url=str(row["url"]),
                    headline=str(row["headline"]),
                    summary=row["summary"],
                    source=row["source"],
                    category=row["category"],
                    published_at=row["published_at"],
                    related=row["related"],
                ):
                    upserts += 1

        log.info(
            "market_news_sync_complete",
            rss_rows=len(rss_rows),
            upserts=upserts,
            lookback_hours=LOOKBACK_HOURS,
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
