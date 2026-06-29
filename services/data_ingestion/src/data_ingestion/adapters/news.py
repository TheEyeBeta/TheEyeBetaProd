"""RSS news ingestion via httpx + feedparser with URL SHA-256 deduplication."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
import structlog
import yaml

from data_ingestion.adapters.base import _CONFIG_DIR, load_active_instruments, make_http_client
from data_ingestion.adapters.news_tickers import extract_tickers
from zinc_schemas.ingestion import NewsRecord, Record

log = structlog.get_logger()

LOOKBACK_DAYS = int(os.environ.get("NEWS_LOOKBACK_DAYS", "1"))


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


API_PROVIDER_LIMIT = _positive_int_from_env("NEWS_API_PROVIDER_LIMIT", 100)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _entry_published_at(entry: dict[str, Any], fallback: date) -> datetime:
    published = entry.get("published") or entry.get("updated")
    if published:
        try:
            parsed = parsedate_to_datetime(str(published))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError):
            pass
    return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)


def _parse_iso_datetime(raw: object, fallback: date) -> datetime:
    if raw is None:
        return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)
    value = str(raw).strip()
    if not value:
        return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)
    try:
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)


def _parse_alpha_vantage_time(raw: object, fallback: date) -> datetime:
    value = str(raw or "").strip()
    if len(value) >= 15:
        try:
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            pass
    return _parse_iso_datetime(value, fallback)


def _parse_unix_datetime(raw: object, fallback: date) -> datetime:
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError, OSError):
        return datetime(fallback.year, fallback.month, fallback.day, 12, 0, tzinfo=UTC)


def _within_window(observed_at: datetime, *, cutoff: date, target_date: date) -> bool:
    pub_date = observed_at.date()
    return cutoff <= pub_date <= target_date


def _split_tickers(raw: object) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        values = raw.replace(";", ",").split(",")
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        values = [raw]
    tickers: set[str] = set()
    for value in values:
        symbol = str(value).strip().upper()
        if symbol:
            tickers.add(symbol)
    return tickers


def _record_from_article(
    *,
    feed_name: str,
    headline: str,
    url: str,
    observed_at: datetime,
    body: str | None,
    language: str,
    seen_hashes: set[str],
    universe: set[str],
    explicit_tickers: set[str] | None = None,
) -> NewsRecord | None:
    link = url.strip()
    title = headline.strip()
    if not link or not title:
        return None
    url_digest = _url_hash(link)
    if url_digest in seen_hashes:
        return None
    seen_hashes.add(url_digest)
    text_blob = f"{title}\n{body or ''}"
    explicit = (explicit_tickers or set()) & universe
    extracted = set(extract_tickers(text_blob, universe))
    tickers = sorted(explicit if explicit else extracted)
    return NewsRecord(
        source="news",
        observed_at=observed_at,
        headline=title,
        url=link,
        url_hash=url_digest,
        feed_name=feed_name,
        body=body.strip() if body else None,
        language=language,
        tickers=tuple(tickers),
    )


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
        published_at = _entry_published_at(entry, target_date)
        if not _within_window(published_at, cutoff=cutoff, target_date=target_date):
            continue
        summary = entry.get("summary")
        body = str(summary).strip() if summary else None
        record = _record_from_article(
            feed_name=feed_name,
            headline=str(entry.get("title", "")).strip() or "(no title)",
            url=str(entry.get("link", "")).strip(),
            observed_at=published_at,
            body=body,
            language=language,
            seen_hashes=seen_hashes,
            universe=universe,
        )
        if record is not None:
            records.append(record)
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
        cutoff = target_date - timedelta(days=max(LOOKBACK_DAYS - 1, 0))
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
            for record in await self._fetch_api_provider_records(
                client,
                cutoff=cutoff,
                target_date=target_date,
                seen_hashes=seen_hashes,
                universe=universe,
            ):
                yield record

    async def _fetch_api_provider_records(
        self,
        client: httpx.AsyncClient,
        *,
        cutoff: date,
        target_date: date,
        seen_hashes: set[str],
        universe: set[str],
    ) -> list[NewsRecord]:
        records: list[NewsRecord] = []
        provider_fetches = (
            ("finnhub", self._fetch_finnhub(client, cutoff, target_date, seen_hashes, universe)),
            (
                "alpha_vantage",
                self._fetch_alpha_vantage(client, cutoff, target_date, seen_hashes, universe),
            ),
            ("newsapi", self._fetch_newsapi(client, cutoff, target_date, seen_hashes, universe)),
            ("tavily", self._fetch_tavily(client, cutoff, target_date, seen_hashes, universe)),
        )
        for provider, fetch in provider_fetches:
            try:
                records.extend(await fetch)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "news_api_provider_failed", provider=provider, error_type=type(exc).__name__
                )
        return records

    async def _fetch_finnhub(
        self,
        client: httpx.AsyncClient,
        cutoff: date,
        target_date: date,
        seen_hashes: set[str],
        universe: set[str],
    ) -> list[NewsRecord]:
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return []
        response = await client.get(
            "https://finnhub.io/api/v1/news",
            params={
                "category": os.environ.get("NEWS_FINNHUB_CATEGORY", "general"),
                "token": api_key,
            },
        )
        response.raise_for_status()
        records: list[NewsRecord] = []
        for item in response.json()[:API_PROVIDER_LIMIT]:
            observed_at = _parse_unix_datetime(item.get("datetime"), target_date)
            if not _within_window(observed_at, cutoff=cutoff, target_date=target_date):
                continue
            explicit_tickers = _split_tickers(item.get("related"))
            source = str(item.get("source") or "finnhub").strip().lower()
            record = _record_from_article(
                feed_name=f"finnhub:{source}",
                headline=str(item.get("headline") or ""),
                url=str(item.get("url") or ""),
                observed_at=observed_at,
                body=str(item.get("summary") or "") or None,
                language="en",
                seen_hashes=seen_hashes,
                universe=universe,
                explicit_tickers=explicit_tickers,
            )
            if record is not None:
                records.append(record)
        log.info("news_api_provider_fetched", provider="finnhub", articles=len(records))
        return records

    async def _fetch_alpha_vantage(
        self,
        client: httpx.AsyncClient,
        cutoff: date,
        target_date: date,
        seen_hashes: set[str],
        universe: set[str],
    ) -> list[NewsRecord]:
        api_key = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get(
            "ALPHA_VANTAGE_API_KEY",
            "",
        )
        if not api_key:
            return []
        response = await client.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "apikey": api_key,
                "sort": "LATEST",
                "limit": str(API_PROVIDER_LIMIT),
                "time_from": cutoff.strftime("%Y%m%dT0000"),
            },
        )
        response.raise_for_status()
        records: list[NewsRecord] = []
        for item in response.json().get("feed", [])[:API_PROVIDER_LIMIT]:
            observed_at = _parse_alpha_vantage_time(item.get("time_published"), target_date)
            if not _within_window(observed_at, cutoff=cutoff, target_date=target_date):
                continue
            explicit_tickers = {
                str(ticker.get("ticker", "")).upper()
                for ticker in item.get("ticker_sentiment", [])
                if isinstance(ticker, dict) and ticker.get("ticker")
            }
            source = str(item.get("source") or "alpha_vantage").strip().lower()
            record = _record_from_article(
                feed_name=f"alpha_vantage:{source}",
                headline=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                observed_at=observed_at,
                body=str(item.get("summary") or "") or None,
                language="en",
                seen_hashes=seen_hashes,
                universe=universe,
                explicit_tickers=explicit_tickers,
            )
            if record is not None:
                records.append(record)
        log.info("news_api_provider_fetched", provider="alpha_vantage", articles=len(records))
        return records

    async def _fetch_newsapi(
        self,
        client: httpx.AsyncClient,
        cutoff: date,
        target_date: date,
        seen_hashes: set[str],
        universe: set[str],
    ) -> list[NewsRecord]:
        api_key = os.environ.get("NEWSAPI_API_KEY") or os.environ.get("NEWS_API_KEY", "")
        if not api_key:
            return []
        response = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "apiKey": api_key,
                "q": os.environ.get("NEWSAPI_QUERY", 'stocks OR equities OR "stock market"'),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": str(min(API_PROVIDER_LIMIT, 100)),
                "from": cutoff.isoformat(),
                "to": target_date.isoformat(),
            },
        )
        response.raise_for_status()
        records: list[NewsRecord] = []
        for item in response.json().get("articles", [])[:API_PROVIDER_LIMIT]:
            observed_at = _parse_iso_datetime(item.get("publishedAt"), target_date)
            if not _within_window(observed_at, cutoff=cutoff, target_date=target_date):
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            source_name = str(source.get("name") or "newsapi").strip().lower()
            body = item.get("description") or item.get("content")
            record = _record_from_article(
                feed_name=f"newsapi:{source_name}",
                headline=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                observed_at=observed_at,
                body=str(body or "") or None,
                language="en",
                seen_hashes=seen_hashes,
                universe=universe,
            )
            if record is not None:
                records.append(record)
        log.info("news_api_provider_fetched", provider="newsapi", articles=len(records))
        return records

    async def _fetch_tavily(
        self,
        client: httpx.AsyncClient,
        cutoff: date,
        target_date: date,
        seen_hashes: set[str],
        universe: set[str],
    ) -> list[NewsRecord]:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return []
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": os.environ.get(
                    "TAVILY_NEWS_QUERY",
                    "latest stock market business finance news",
                ),
                "topic": "news",
                "days": LOOKBACK_DAYS,
                "max_results": min(API_PROVIDER_LIMIT, 20),
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        records: list[NewsRecord] = []
        for item in response.json().get("results", [])[:API_PROVIDER_LIMIT]:
            observed_at = _parse_iso_datetime(item.get("published_date"), target_date)
            if not _within_window(observed_at, cutoff=cutoff, target_date=target_date):
                continue
            record = _record_from_article(
                feed_name="tavily:news",
                headline=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                observed_at=observed_at,
                body=str(item.get("content") or "") or None,
                language="en",
                seen_hashes=seen_hashes,
                universe=universe,
            )
            if record is not None:
                records.append(record)
        log.info("news_api_provider_fetched", provider="tavily", articles=len(records))
        return records
