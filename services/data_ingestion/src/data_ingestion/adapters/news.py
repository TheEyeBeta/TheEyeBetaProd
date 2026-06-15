"""RSS news ingestion via httpx + feedparser with URL SHA-256 deduplication."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import structlog
import yaml

from data_ingestion.adapters.base import _CONFIG_DIR, make_http_client
from zinc_schemas.ingestion import NewsRecord, Record

log = structlog.get_logger()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _entry_published_date(entry: dict[str, Any]) -> date | None:
    published = entry.get("published") or entry.get("updated")
    if not published:
        return None
    try:
        return parsedate_to_datetime(str(published)).astimezone(UTC).date()
    except (TypeError, ValueError):
        return None


def _parse_feed(
    content: str,
    *,
    feed_name: str,
    language: str,
    target_date: date,
    seen_hashes: set[str],
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
        pub_date = _entry_published_date(entry)
        if pub_date is None or pub_date != target_date:
            continue
        seen_hashes.add(url_digest)
        title = str(entry.get("title", "")).strip() or "(no title)"
        summary = entry.get("summary")
        body = str(summary).strip() if summary else None
        published_at = datetime(
            pub_date.year,
            pub_date.month,
            pub_date.day,
            12,
            0,
            tzinfo=UTC,
        )
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
        """Yield news articles published on target_date (UTC calendar day)."""
        seen_hashes: set[str] = set()
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
                        target_date=target_date,
                        seen_hashes=seen_hashes,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("news_feed_failed", feed=name, url=url, error=str(exc))
                    continue
                log.info("news_feed_fetched", feed=name, articles=len(records))
                for record in records:
                    yield record
