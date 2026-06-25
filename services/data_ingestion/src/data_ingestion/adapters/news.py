"""RSS news ingestion via httpx + feedparser with URL SHA-256 deduplication."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import structlog
import yaml

from data_ingestion.adapters.base import _CONFIG_DIR, load_active_instruments, make_http_client
from data_ingestion.adapters.news_tickers import extract_tickers
from zinc_schemas.ingestion import NewsRecord, Record

log = structlog.get_logger()

LOOKBACK_DAYS = int(os.environ.get("NEWS_LOOKBACK_DAYS", "7"))


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _entry_published_at(entry: dict[str, Any], fallback: date) -> datetime:
    published = entry.get("published") or entry.get("updated")
    if published:
        try:
            return parsedate_to_datetime(str(published)).astimezone(UTC)
        except (TypeError, ValueError):
            pass
    return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)


def _parse_feed(
    content: str,
    *,
    feed_name: str,
    language: str,
    cutoff: date,
    target_date: date,
    seen_hashes: set[str],
    universe: set[str],
) -> list[NewsRecord]:
    parsed = feedparser.parse(content)
    records: list[NewsRecord] = []
    for entry in parsed.entries:
        link = str(entry.get("link", "")).strip()
        if not link:
            continue
        url_digest = _url_hash(link)
        if url_digest in seen_hashes:
            continue
        published_at = _entry_published_at(entry, target_date)
        pub_date = published_at.date()
        if pub_date < cutoff or pub_date > target_date:
            continue
        seen_hashes.add(url_digest)
        title = str(entry.get("title", "")).strip() or "(no title)"
        summary = entry.get("summary")
        body = str(summary).strip() if summary else None
        text_blob = f"{title}\n{body or ''}"
        tickers = extract_tickers(text_blob, universe)
        records.append(
            NewsRecord(
                source="news",
                observed_at=published_at,
                headline=title,
                url=link,
                url_hash=url_digest,
                feed_name=feed_name,
                body=body,
                language=language,
                tickers=tickers,
            )
        )
    return records


def _load_feeds() -> list[dict[str, str]]:
    config = yaml.safe_load((_CONFIG_DIR / "news_sources.yaml").read_text(encoding="utf-8"))
    return list(config.get("feeds", []))


class NewsAdapter:
    """Poll configured RSS feeds and yield deduplicated news records."""

    name = "news"

    def __init__(self, *, feeds: list[dict[str, str]] | None = None) -> None:
        self._feeds = feeds or _load_feeds()

    async def fetch(self, target_date: date) -> AsyncIterator[Record]:
        """Yield news articles within NEWS_LOOKBACK_DAYS ending on target_date."""
        cutoff = target_date - timedelta(days=LOOKBACK_DAYS)
        seen_hashes: set[str] = set()
        instruments = await load_active_instruments()
        universe = {str(row["symbol"]).upper() for row in instruments}

        async with make_http_client() as client:
            for feed in self._feeds:
                name = str(feed["name"])
                url = str(feed["url"])
                language = str(feed.get("language", "en"))
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    records = _parse_feed(
                        response.text,
                        feed_name=name,
                        language=language,
                        cutoff=cutoff,
                        target_date=target_date,
                        seen_hashes=seen_hashes,
                        universe=universe,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("news_feed_failed", feed=name, url=url, error=str(exc))
                    continue
                log.info(
                    "news_feed_fetched",
                    feed=name,
                    articles=len(records),
                    lookback_days=LOOKBACK_DAYS,
                )
                for record in records:
                    yield record
