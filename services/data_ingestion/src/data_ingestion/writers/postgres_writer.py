"""PostgreSQL bulk writer for price bars and macro points.

Uses psycopg3 async COPY into a temp table, then INSERT ... ON CONFLICT DO NOTHING
to the hypertable.  This pattern is idempotent and avoids duplicate key errors on
re-runs.
"""

from __future__ import annotations

import os

import psycopg
import structlog

from data_ingestion.adapters.base import MacroPoint, PriceBar

log = structlog.get_logger()


def _get_ingest_dsn() -> str:
    """Return a psycopg-native DSN from INGEST_DATABASE_URL.

    Strips any SQLAlchemy driver prefix (``+asyncpg`` / ``+psycopg``).

    Returns:
        A plain ``postgresql://`` DSN suitable for psycopg.

    Raises:
        EnvironmentError: If INGEST_DATABASE_URL is not set.
    """
    raw = os.environ.get("INGEST_DATABASE_URL", "")
    if not raw:
        raise EnvironmentError("INGEST_DATABASE_URL environment variable is not set")
    for suffix in ("+asyncpg", "+psycopg"):
        raw = raw.replace(suffix, "")
    return raw


class PostgresWriter:
    """Writes ingested data to theeyebeta.prices_daily and macro_indicators.

    Each write method opens a fresh connection from INGEST_DATABASE_URL (tb_app
    credentials), creates a temp table, COPY-loads the data, then INSERT … ON
    CONFLICT DO NOTHING into the hypertable.  The connection is closed after each
    call.

    Args:
        dsn: Optional override for INGEST_DATABASE_URL (mainly for tests).
    """

    def __init__(self, dsn: str | None = None) -> None:
        """Initialise the writer, resolving the DSN from env if not provided."""
        self._dsn = dsn or _get_ingest_dsn()

    async def write_prices_daily(self, bars: list[PriceBar]) -> int:
        """Bulk-insert price bars into theeyebeta.prices_daily.

        Args:
            bars: List of PriceBar objects to persist.

        Returns:
            Number of rows actually inserted (excludes duplicates skipped by
            ON CONFLICT DO NOTHING).
        """
        if not bars:
            return 0

        aconn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=False)
        try:
            async with aconn:
                async with aconn.cursor() as cur:
                    await cur.execute(
                        """
                        CREATE TEMP TABLE _ingest_prices (
                            instrument_id bigint  NOT NULL,
                            ts            timestamptz NOT NULL,
                            open          numeric(18,6) NOT NULL,
                            high          numeric(18,6) NOT NULL,
                            low           numeric(18,6) NOT NULL,
                            close         numeric(18,6) NOT NULL,
                            adj_close     numeric(18,6),
                            volume        bigint  NOT NULL,
                            source        text    NOT NULL
                        ) ON COMMIT DROP
                        """
                    )

                    async with cur.copy(
                        "COPY _ingest_prices "
                        "(instrument_id, ts, open, high, low, close, adj_close, volume, source) "
                        "FROM STDIN"
                    ) as copy:
                        for bar in bars:
                            await copy.write_row(
                                [
                                    bar.instrument_id,
                                    bar.ts,
                                    bar.open,
                                    bar.high,
                                    bar.low,
                                    bar.close,
                                    bar.adj_close,
                                    bar.volume,
                                    bar.source,
                                ]
                            )

                    await cur.execute(
                        """
                        INSERT INTO theeyebeta.prices_daily
                            (instrument_id, ts, open, high, low, close,
                             adj_close, volume, source, ingested_at)
                        SELECT
                            instrument_id, ts, open, high, low, close,
                            adj_close, volume, source, NOW()
                        FROM _ingest_prices
                        ON CONFLICT (instrument_id, ts) DO NOTHING
                        """
                    )
                    rows_inserted = cur.rowcount

                await aconn.commit()

        except Exception:
            await aconn.rollback()
            raise

        log.info(
            "prices_daily_written",
            rows_attempted=len(bars),
            rows_inserted=rows_inserted,
        )
        return rows_inserted

    async def write_macro(self, points: list[MacroPoint]) -> int:
        """Bulk-insert macro observations into theeyebeta.macro_indicators.

        Args:
            points: List of MacroPoint objects to persist.

        Returns:
            Number of rows actually inserted (excludes duplicates).
        """
        if not points:
            return 0

        aconn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=False)
        try:
            async with aconn:
                async with aconn.cursor() as cur:
                    await cur.execute(
                        """
                        CREATE TEMP TABLE _ingest_macro (
                            series_code text          NOT NULL,
                            ts          timestamptz   NOT NULL,
                            value       numeric(20,6) NOT NULL,
                            source      text          NOT NULL
                        ) ON COMMIT DROP
                        """
                    )

                    async with cur.copy(
                        "COPY _ingest_macro (series_code, ts, value, source) FROM STDIN"
                    ) as copy:
                        for pt in points:
                            await copy.write_row(
                                [pt.series_code, pt.ts, pt.value, pt.source]
                            )

                    await cur.execute(
                        """
                        INSERT INTO theeyebeta.macro_indicators
                            (series_code, ts, value, source)
                        SELECT series_code, ts, value, source
                        FROM _ingest_macro
                        ON CONFLICT (series_code, ts) DO NOTHING
                        """
                    )
                    rows_inserted = cur.rowcount

                await aconn.commit()

        except Exception:
            await aconn.rollback()
            raise

        log.info(
            "macro_indicators_written",
            series_count=len({p.series_code for p in points}),
            rows_attempted=len(points),
            rows_inserted=rows_inserted,
        )
        return rows_inserted
