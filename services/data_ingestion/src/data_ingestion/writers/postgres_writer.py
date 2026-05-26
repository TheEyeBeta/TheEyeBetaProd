"""PostgreSQL writer using asyncpg COPY and pooled connections."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime
from uuid import UUID

import asyncpg
import structlog
from zinc_schemas.ingestion import (
    FundamentalRecord,
    IntradayBarRecord,
    MacroRecord,
    NewsEmbeddingRecord,
    NewsRecord,
    PriceDailyRecord,
    Record,
)

from data_ingestion.observability import observe_duration, record_written, span

log = structlog.get_logger()

_POOL: asyncpg.Pool | None = None
_POOL_MAX_SIZE = 10


def _dsn() -> str:
    raw = os.environ.get("INGEST_DATABASE_URL", "")
    if not raw:
        raise OSError("INGEST_DATABASE_URL environment variable is not set")
    return re.sub(r"\+\w+", "", raw, count=1)


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool (lazy init, max 10 connections)."""
    global _POOL  # noqa: PLW0603
    if _POOL is None:
        _POOL = await asyncpg.create_pool(
            _dsn(),
            min_size=1,
            max_size=_POOL_MAX_SIZE,
            command_timeout=120,
        )
    return _POOL


async def close_pool() -> None:
    """Close the shared pool (called on app shutdown)."""
    global _POOL  # noqa: PLW0603
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


class PostgresWriter:
    """Bulk writer with asyncpg COPY and optional upsert for backfills."""

    def __init__(self, conn: asyncpg.Connection, *, upsert: bool = False) -> None:
        self._conn = conn
        self._upsert = upsert

    async def write_records(
        self,
        records: list[Record],
        *,
        adapter: str = "pipeline",
        market: str = "all",
    ) -> dict[str, int]:
        """Route heterogeneous records to table-specific writers."""
        prices: list[PriceDailyRecord] = []
        macro: list[MacroRecord] = []
        intraday: list[IntradayBarRecord] = []
        news: list[NewsRecord] = []
        embeddings: list[NewsEmbeddingRecord] = []
        fundamentals: list[FundamentalRecord] = []
        for record in records:
            match record:
                case PriceDailyRecord():
                    prices.append(record)
                case MacroRecord():
                    macro.append(record)
                case IntradayBarRecord():
                    intraday.append(record)
                case NewsRecord():
                    news.append(record)
                case NewsEmbeddingRecord():
                    embeddings.append(record)
                case FundamentalRecord():
                    fundamentals.append(record)

        async with observe_duration(adapter, market):
            async with span("writer.write_records", adapter=adapter, market=market):
                totals = {
                    "prices_daily": await self.write_prices_daily(prices),
                    "macro_indicators": await self.write_macro(macro),
                    "prices_intraday": await self.write_prices_intraday(intraday),
                    "news_articles": await self.write_news(news),
                    "news_embeddings": await self.write_news_embeddings(embeddings),
                    "fundamentals": await self.write_fundamentals(fundamentals),
                }
        for table, count in totals.items():
            record_written(adapter, market, count)
        return totals

    async def write_prices_daily(self, bars: list[PriceDailyRecord]) -> int:
        if not bars:
            return 0
        async with span("writer.write_prices_daily", rows=len(bars)):
            await self._conn.execute(
                """
                CREATE TEMP TABLE _ingest_prices (
                    instrument_id bigint NOT NULL,
                    ts timestamptz NOT NULL,
                    open numeric(18,6) NOT NULL,
                    high numeric(18,6) NOT NULL,
                    low numeric(18,6) NOT NULL,
                    close numeric(18,6) NOT NULL,
                    adj_close numeric(18,6),
                    volume bigint NOT NULL,
                    source text NOT NULL
                ) ON COMMIT DROP
                """
            )
            await self._conn.copy_records_to_table(
                "_ingest_prices",
                records=[
                    (
                        b.instrument_id,
                        b.observed_at,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.adj_close,
                        b.volume,
                        b.source,
                    )
                    for b in bars
                ],
                columns=[
                    "instrument_id",
                    "ts",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_close",
                    "volume",
                    "source",
                ],
            )
            conflict = (
                """
                ON CONFLICT (instrument_id, ts) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    adj_close = EXCLUDED.adj_close,
                    volume = EXCLUDED.volume,
                    source = EXCLUDED.source,
                    ingested_at = NOW()
                """
                if self._upsert
                else "ON CONFLICT (instrument_id, ts) DO NOTHING"
            )
            result = await self._conn.execute(
                f"""
                INSERT INTO theeyebeta.prices_daily
                    (instrument_id, ts, open, high, low, close,
                     adj_close, volume, source, ingested_at)
                SELECT instrument_id, ts, open, high, low, close,
                       adj_close, volume, source, NOW()
                FROM _ingest_prices
                {conflict}
                """
            )
        return _parse_insert_count(result)

    async def write_prices_intraday(self, bars: list[IntradayBarRecord]) -> int:
        if not bars:
            return 0
        async with span("writer.write_prices_intraday", rows=len(bars)):
            await self._conn.execute(
                """
                CREATE TEMP TABLE _ingest_intraday (
                    instrument_id bigint NOT NULL,
                    ts timestamptz NOT NULL,
                    bar_seconds int NOT NULL,
                    open numeric(18,6) NOT NULL,
                    high numeric(18,6) NOT NULL,
                    low numeric(18,6) NOT NULL,
                    close numeric(18,6) NOT NULL,
                    volume bigint NOT NULL,
                    source text NOT NULL
                ) ON COMMIT DROP
                """
            )
            await self._conn.copy_records_to_table(
                "_ingest_intraday",
                records=[
                    (
                        b.instrument_id,
                        b.observed_at,
                        b.bar_seconds,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.volume,
                        b.source,
                    )
                    for b in bars
                ],
                columns=[
                    "instrument_id",
                    "ts",
                    "bar_seconds",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "source",
                ],
            )
            conflict = (
                """
                ON CONFLICT (instrument_id, bar_seconds, ts) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    source = EXCLUDED.source
                """
                if self._upsert
                else "ON CONFLICT (instrument_id, bar_seconds, ts) DO NOTHING"
            )
            result = await self._conn.execute(
                f"""
                INSERT INTO theeyebeta.prices_intraday
                    (instrument_id, ts, bar_seconds, open, high, low, close, volume, source)
                SELECT instrument_id, ts, bar_seconds, open, high, low, close, volume, source
                FROM _ingest_intraday
                {conflict}
                """
            )
        return _parse_insert_count(result)

    async def write_macro(self, points: list[MacroRecord]) -> int:
        if not points:
            return 0
        async with span("writer.write_macro", rows=len(points)):
            await self._conn.execute(
                """
                CREATE TEMP TABLE _ingest_macro (
                    series_code text NOT NULL,
                    ts timestamptz NOT NULL,
                    value numeric(20,6) NOT NULL,
                    source text NOT NULL
                ) ON COMMIT DROP
                """
            )
            await self._conn.copy_records_to_table(
                "_ingest_macro",
                records=[(p.series_code, p.observed_at, p.value, p.source) for p in points],
                columns=["series_code", "ts", "value", "source"],
            )
            conflict = (
                """
                ON CONFLICT (series_code, ts) DO UPDATE SET
                    value = EXCLUDED.value,
                    source = EXCLUDED.source
                """
                if self._upsert
                else "ON CONFLICT (series_code, ts) DO NOTHING"
            )
            result = await self._conn.execute(
                f"""
                INSERT INTO theeyebeta.macro_indicators (series_code, ts, value, source)
                SELECT series_code, ts, value, source FROM _ingest_macro
                {conflict}
                """
            )
        return _parse_insert_count(result)

    async def write_news(self, articles: list[NewsRecord]) -> int:
        if not articles:
            return 0
        async with span("writer.write_news", rows=len(articles)):
            await self._conn.execute(
                """
                CREATE TEMP TABLE _ingest_news (
                    published_at timestamptz NOT NULL,
                    source text NOT NULL,
                    headline text NOT NULL,
                    body text,
                    url text NOT NULL,
                    language char(2) NOT NULL,
                    tickers text[] NOT NULL
                ) ON COMMIT DROP
                """
            )
            await self._conn.copy_records_to_table(
                "_ingest_news",
                records=[
                    (
                        a.observed_at,
                        a.feed_name,
                        a.headline,
                        a.body,
                        a.url,
                        a.language[:2],
                        list(a.tickers),
                    )
                    for a in articles
                ],
                columns=[
                    "published_at",
                    "source",
                    "headline",
                    "body",
                    "url",
                    "language",
                    "tickers",
                ],
            )
            result = await self._conn.execute(
                """
                INSERT INTO theeyebeta.news_articles
                    (published_at, source, headline, body, url, language, tickers)
                SELECT n.published_at, n.source, n.headline, n.body, n.url, n.language, n.tickers
                FROM _ingest_news n
                WHERE NOT EXISTS (
                    SELECT 1 FROM theeyebeta.news_articles e
                    WHERE e.url IS NOT NULL AND e.url = n.url
                )
                """
            )
        return _parse_insert_count(result)

    async def write_news_embeddings(self, rows: list[NewsEmbeddingRecord]) -> int:
        if not rows:
            return 0
        inserted = 0
        conflict = (
            """
            ON CONFLICT (article_id) DO UPDATE SET
                model = EXCLUDED.model,
                embedding = EXCLUDED.embedding,
                created_at = NOW()
            """
            if self._upsert
            else "ON CONFLICT (article_id) DO NOTHING"
        )
        async with span("writer.write_news_embeddings", rows=len(rows)):
            for row in rows:
                article_id = await self._conn.fetchval(
                    "SELECT id FROM theeyebeta.news_articles WHERE url = $1 LIMIT 1",
                    row.article_url,
                )
                if article_id is None:
                    continue
                result = await self._conn.execute(
                    f"""
                    INSERT INTO theeyebeta.news_embeddings (article_id, model, embedding)
                    VALUES ($1, $2, $3::vector)
                    {conflict}
                    """,
                    article_id,
                    row.model,
                    _vector_literal(row.embedding),
                )
                inserted += _parse_insert_count(result)
        return inserted

    async def write_fundamentals(self, rows: list[FundamentalRecord]) -> int:
        if not rows:
            return 0
        async with span("writer.write_fundamentals", rows=len(rows)):
            await self._conn.execute(
                """
                CREATE TEMP TABLE _ingest_fundamentals (
                    instrument_id bigint NOT NULL,
                    period_end date NOT NULL,
                    period_type text NOT NULL,
                    revenue numeric(20,2),
                    net_income numeric(20,2),
                    eps numeric(12,4),
                    pe_ratio numeric(12,4),
                    pb_ratio numeric(12,4),
                    debt_to_equity numeric(12,4),
                    roe numeric(12,6),
                    gross_margin numeric(12,6),
                    free_cash_flow numeric(20,2),
                    raw jsonb NOT NULL,
                    source text NOT NULL
                ) ON COMMIT DROP
                """
            )
            await self._conn.copy_records_to_table(
                "_ingest_fundamentals",
                records=[
                    (
                        r.instrument_id,
                        r.period_end,
                        r.period_type,
                        r.revenue,
                        r.net_income,
                        r.eps,
                        r.pe_ratio,
                        r.pb_ratio,
                        r.debt_to_equity,
                        r.roe,
                        r.gross_margin,
                        r.free_cash_flow,
                        json.dumps(r.raw),
                        r.source,
                    )
                    for r in rows
                ],
                columns=[
                    "instrument_id",
                    "period_end",
                    "period_type",
                    "revenue",
                    "net_income",
                    "eps",
                    "pe_ratio",
                    "pb_ratio",
                    "debt_to_equity",
                    "roe",
                    "gross_margin",
                    "free_cash_flow",
                    "raw",
                    "source",
                ],
            )
            conflict = (
                """
                ON CONFLICT (instrument_id, period_end, period_type, source) DO UPDATE SET
                    revenue = EXCLUDED.revenue,
                    net_income = EXCLUDED.net_income,
                    eps = EXCLUDED.eps,
                    pe_ratio = EXCLUDED.pe_ratio,
                    pb_ratio = EXCLUDED.pb_ratio,
                    debt_to_equity = EXCLUDED.debt_to_equity,
                    roe = EXCLUDED.roe,
                    gross_margin = EXCLUDED.gross_margin,
                    free_cash_flow = EXCLUDED.free_cash_flow,
                    raw = EXCLUDED.raw,
                    ingested_at = NOW()
                """
                if self._upsert
                else "ON CONFLICT (instrument_id, period_end, period_type, source) DO NOTHING"
            )
            result = await self._conn.execute(
                f"""
                INSERT INTO theeyebeta.fundamentals (
                    instrument_id, period_end, period_type, revenue, net_income, eps,
                    pe_ratio, pb_ratio, debt_to_equity, roe, gross_margin,
                    free_cash_flow, raw, source
                )
                SELECT instrument_id, period_end, period_type, revenue, net_income, eps,
                       pe_ratio, pb_ratio, debt_to_equity, roe, gross_margin,
                       free_cash_flow, raw, source
                FROM _ingest_fundamentals
                {conflict}
                """
            )
        return _parse_insert_count(result)

    async def fetch_market_daily_frame(
        self,
        market: str,
        trade_date: date,
    ) -> list[asyncpg.Record]:
        """Load daily OHLCV joined with symbols for one market calendar day."""
        day_start = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
        day_end = datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            23,
            59,
            59,
            tzinfo=UTC,
        )
        return await self._conn.fetch(
            """
            SELECT i.symbol, e.code AS exchange_code, p.ts, p.open, p.high, p.low,
                   p.close, p.adj_close, p.volume, p.source
            FROM theeyebeta.prices_daily p
            JOIN theeyebeta.instruments i ON i.id = p.instrument_id
            JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
            WHERE p.ts >= $1 AND p.ts <= $2
              AND CASE e.code
                    WHEN 'XNAS' THEN 'US' WHEN 'XNYS' THEN 'US'
                    WHEN 'XHKG' THEN 'HK' WHEN 'XTKS' THEN 'JP'
                    WHEN 'XTAI' THEN 'TW' WHEN 'XSHG' THEN 'CN'
                    WHEN 'XSHE' THEN 'CN' ELSE 'OTHER'
                  END = $3
            ORDER BY i.symbol
            """,
            day_start,
            day_end,
            market,
        )

    async def register_snapshot(
        self,
        *,
        market: str,
        trade_date: date,
        blob_uri: str,
        sha256_hex: str,
        row_count: int,
        schema_version: int = 1,
    ) -> UUID:
        """Upsert a data_snapshots catalog row."""
        digest = bytes.fromhex(sha256_hex)
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.data_snapshots
                (market, trade_date, schema_version, blob_uri, blob_sha256, universe_size,
                 packager_git_sha)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (market, trade_date, schema_version) DO UPDATE SET
                blob_uri = EXCLUDED.blob_uri,
                blob_sha256 = EXCLUDED.blob_sha256,
                universe_size = EXCLUDED.universe_size,
                packaged_at = NOW()
            RETURNING id
            """,
            market,
            trade_date,
            schema_version,
            blob_uri,
            digest,
            row_count,
            os.environ.get("GIT_COMMIT", "dev"),
        )
        return row["id"]


def _parse_insert_count(status: str) -> int:
    """Parse asyncpg ``INSERT 0 N`` status string."""
    parts = status.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


def _vector_literal(values: tuple[float, ...]) -> str:
    inner = ",".join(str(v) for v in values)
    return f"[{inner}]"
