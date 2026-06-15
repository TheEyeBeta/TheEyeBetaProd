"""Daily macro regime worker.

CLI examples:
    python -m workers.macro_regime_worker --date 2026-06-10
    python -m workers.macro_regime_worker --date 2026-06-10 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

import asyncpg
import yfinance as yf

from workers.base_worker import BaseWorker, WorkerResult
from workers.fred_client import FredClient
from workers.macro_calculations import (
    annualized_qoq_pct,
    classify_credit_environment,
    classify_dollar_regime,
    classify_rate_environment,
    classify_volatility_regime,
    classify_yield_curve,
    compute_style_tilts,
)

INDICATOR_GROWTH_SERIES = {
    "cpi": "CPIAUCSL",
    "gdp": "GDPC1",
}

REGIME_COLUMNS = [
    "id",
    "as_of_date",
    "fed_funds_rate",
    "yield_10y",
    "yield_2y",
    "spread_2s10s",
    "vix",
    "dxy",
    "hy_oas_bps",
    "rate_environment",
    "yield_curve",
    "credit_environment",
    "volatility_regime",
    "dollar_regime",
    "style_tilts",
    "data_source",
    "computed_at",
    "sp500_level",
    "sp500_change_pct",
    "nasdaq_level",
    "nasdaq_change_pct",
    "cpi",
    "gdp",
    "fed_funds_change_30d",
    "yield_10y_change_30d",
    "yield_2y_change_30d",
    "spread_2s10s_change_30d",
    "dxy_change_5d",
    "dxy_change_30d",
    "vix_change_5d",
    "vix_pct_rank_1y",
    "hy_oas_change_30d",
    "sp500_change_5d_pct",
    "sp500_change_30d_pct",
    "nasdaq_change_5d_pct",
    "nasdaq_change_30d_pct",
    "cpi_surprise",
    "cpi_yoy_pct",
    "gdp_qoq_pct",
]

FRED_RAW_SERIES = {
    "fed_funds_rate": "DFF",
    "yield_2y": "DGS2",
    "yield_10y": "DGS10",
    "hy_oas_bps": "BAMLH0A0HYM2",
    "cpi": "CPIAUCSL",
    "gdp": "GDPC1",
}

YFINANCE_TICKERS = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
}


def _as_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 6)))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class MacroRegimeWorker(BaseWorker):
    """Build one daily canonical macro regime snapshot."""

    worker_name = "MacroRegimeWorker"
    worker_type = "macro"
    display_name = "Macro Regime Worker"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        fred_client: FredClient | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
        self.fred = fred_client or FredClient()

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        if not await self._is_trading_day(conn, trade_date):
            return WorkerResult(
                records_written=0,
                records_expected=1,
                metadata={"skipped": True, "reason": "non_trading_day"},
            )

        raw = await self._fetch_raw_inputs(trade_date)
        if dry_run:
            row = await self._compute_dry_run_row(conn, trade_date, raw)
            row_dict = dict(row)
            cpi_yoy, gdp_qoq = await self._compute_growth_from_indicators(conn)
            row_dict["cpi_yoy_pct"] = cpi_yoy
            row_dict["gdp_qoq_pct"] = gdp_qoq
            completed = self._classify_row(row_dict)
            print(json.dumps(completed, indent=2, sort_keys=True, default=_json_default))
            return WorkerResult(
                records_written=0,
                records_expected=1,
                metadata={"dry_run": True, "row": completed},
            )

        async with conn.transaction():
            await self._upsert_canonical_raw(conn, trade_date, raw)
            await self._update_canonical_derived(conn)
            await self._update_growth_from_indicators(conn, trade_date)
            row = await self._fetch_canonical(conn, trade_date)
            classified = self._classify_row(dict(row))
            await self._update_canonical_classification(conn, trade_date, classified)
            await self._fetch_canonical(conn, trade_date)

        return WorkerResult(
            records_written=1,
            records_expected=1,
            metadata={
                "as_of_date": trade_date.isoformat(),
                "rate_environment": classified["rate_environment"],
                "yield_curve": classified["yield_curve"],
                "credit_environment": classified["credit_environment"],
                "volatility_regime": classified["volatility_regime"],
                "dollar_regime": classified["dollar_regime"],
            },
        )

    async def _is_trading_day(self, conn: asyncpg.Connection, trade_date: date) -> bool:
        value = await conn.fetchval(
            """
            SELECT is_trading_day
              FROM theeyebeta.trading_calendar
             WHERE calendar_date = $1
             LIMIT 1
            """,
            trade_date,
        )
        if value is None:
            return trade_date.weekday() < 5
        return bool(value)

    async def _fetch_raw_inputs(self, trade_date: date) -> dict[str, float | None]:
        async def latest(field: str, series_id: str) -> tuple[str, float]:
            obs = await self.fred.latest_value(series_id, as_of=trade_date)
            value = obs.value * 100.0 if field == "hy_oas_bps" else obs.value
            return field, value

        fred_pairs = await asyncio.gather(
            *(latest(field, series_id) for field, series_id in FRED_RAW_SERIES.items()),
        )
        yfinance_quotes = await asyncio.gather(
            *(
                self._fetch_yfinance_quote(ticker, trade_date)
                for ticker in YFINANCE_TICKERS.values()
            ),
        )
        quotes = dict(zip(YFINANCE_TICKERS, yfinance_quotes, strict=True))
        raw: dict[str, float | None] = dict(fred_pairs)
        raw["spread_2s10s"] = None
        if raw["yield_10y"] is not None and raw["yield_2y"] is not None:
            raw["spread_2s10s"] = raw["yield_10y"] - raw["yield_2y"]
        raw["vix"] = quotes["vix"]["close"]
        raw["dxy"] = quotes["dxy"]["close"]
        raw["sp500_level"] = quotes["sp500"]["close"]
        raw["sp500_change_pct"] = quotes["sp500"]["change_pct"]
        raw["nasdaq_level"] = quotes["nasdaq"]["close"]
        raw["nasdaq_change_pct"] = quotes["nasdaq"]["change_pct"]
        return raw

    async def _fetch_yfinance_quote(self, ticker: str, trade_date: date) -> dict[str, float | None]:
        def fetch() -> dict[str, float | None]:
            start = trade_date - timedelta(days=10)
            end = trade_date + timedelta(days=1)
            frame = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if frame.empty:
                raise ValueError(f"No yfinance rows for {ticker} on or before {trade_date}")
            close = frame["Close"]
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            close = close.dropna()
            close = close[close.index.date <= trade_date]
            if close.empty:
                raise ValueError(f"No yfinance close for {ticker} on or before {trade_date}")
            latest = float(close.iloc[-1])
            previous = float(close.iloc[-2]) if len(close) >= 2 else None
            change_pct = None
            if previous and previous > 0:
                change_pct = (latest / previous - 1.0) * 100.0
            return {"close": latest, "change_pct": change_pct}

        return await asyncio.to_thread(fetch)

    async def _upsert_canonical_raw(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        raw: dict[str, float | None],
    ) -> int:
        row = await conn.fetchrow(
            """
            INSERT INTO theeyebeta.macro_regime_snapshots
                (as_of_date, fed_funds_rate, yield_10y, yield_2y, spread_2s10s,
                 vix, dxy, hy_oas_bps, rate_environment, yield_curve,
                 credit_environment, volatility_regime, dollar_regime, style_tilts,
                 data_source, computed_at, sp500_level, sp500_change_pct,
                 nasdaq_level, nasdaq_change_pct, cpi, gdp, cpi_surprise)
            VALUES (
                 $1, $2, $3, $4, $5,
                 $6, $7, $8, 'unknown', 'unknown',
                 'unknown', 'unknown', 'unknown', '{}'::jsonb,
                 'fred+yfinance', now(), $9, $10,
                 $11, $12, $13, $14, NULL
            )
            ON CONFLICT (as_of_date) DO UPDATE SET
                 fed_funds_rate = EXCLUDED.fed_funds_rate,
                 yield_10y = EXCLUDED.yield_10y,
                 yield_2y = EXCLUDED.yield_2y,
                 spread_2s10s = EXCLUDED.spread_2s10s,
                 vix = EXCLUDED.vix,
                 dxy = EXCLUDED.dxy,
                 hy_oas_bps = EXCLUDED.hy_oas_bps,
                 data_source = EXCLUDED.data_source,
                 computed_at = now(),
                 sp500_level = EXCLUDED.sp500_level,
                 sp500_change_pct = EXCLUDED.sp500_change_pct,
                 nasdaq_level = EXCLUDED.nasdaq_level,
                 nasdaq_change_pct = EXCLUDED.nasdaq_change_pct,
                 cpi = EXCLUDED.cpi,
                 gdp = EXCLUDED.gdp,
                 cpi_surprise = NULL
            RETURNING id
            """,
            trade_date,
            _as_decimal(raw["fed_funds_rate"]),
            _as_decimal(raw["yield_10y"]),
            _as_decimal(raw["yield_2y"]),
            _as_decimal(raw["spread_2s10s"]),
            _as_decimal(raw["vix"]),
            _as_decimal(raw["dxy"]),
            _as_decimal(raw["hy_oas_bps"]),
            _as_decimal(raw["sp500_level"]),
            _as_decimal(raw["sp500_change_pct"]),
            _as_decimal(raw["nasdaq_level"]),
            _as_decimal(raw["nasdaq_change_pct"]),
            _as_decimal(raw["cpi"]),
            _as_decimal(raw["gdp"]),
        )
        return int(row["id"])

    async def _compute_growth_from_indicators(
        self,
        conn: asyncpg.Connection,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Return CPI YoY and annualised GDP QoQ from ``macro_indicators`` offsets."""
        cpi_rows = await conn.fetch(
            """
            SELECT value
              FROM theeyebeta.macro_indicators
             WHERE series_code = $1
             ORDER BY ts DESC
             LIMIT 13
            """,
            INDICATOR_GROWTH_SERIES["cpi"],
        )
        gdp_rows = await conn.fetch(
            """
            SELECT value
              FROM theeyebeta.macro_indicators
             WHERE series_code = $1
             ORDER BY ts DESC
             LIMIT 2
            """,
            INDICATOR_GROWTH_SERIES["gdp"],
        )

        cpi_yoy: Decimal | None = None
        if len(cpi_rows) >= 13:
            latest = float(cpi_rows[0]["value"])
            year_ago = float(cpi_rows[12]["value"])
            if year_ago > 0:
                cpi_yoy = _as_decimal((latest / year_ago - 1.0) * 100.0)

        gdp_qoq: Decimal | None = None
        if len(gdp_rows) >= 2:
            current = float(gdp_rows[0]["value"])
            prior = float(gdp_rows[1]["value"])
            qoq = annualized_qoq_pct(current, prior)
            if qoq is not None:
                gdp_qoq = _as_decimal(qoq)

        return cpi_yoy, gdp_qoq

    async def _update_growth_from_indicators(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
    ) -> None:
        """Persist CPI YoY and GDP QoQ sourced from indicator observation history."""
        cpi_yoy, gdp_qoq = await self._compute_growth_from_indicators(conn)
        await conn.execute(
            """
            UPDATE theeyebeta.macro_regime_snapshots
               SET cpi_yoy_pct = $2,
                   gdp_qoq_pct = $3
             WHERE as_of_date = $1
            """,
            trade_date,
            cpi_yoy,
            gdp_qoq,
        )

    async def _update_canonical_derived(self, conn: asyncpg.Connection) -> None:
        """Recompute derived macro deltas using trading-day lookbacks, not row offsets."""
        await conn.execute(
            """
            WITH trading_days AS (
                SELECT
                    calendar_date,
                    LAG(calendar_date, 21) OVER (ORDER BY calendar_date) AS lag_21d,
                    LAG(calendar_date, 5) OVER (ORDER BY calendar_date) AS lag_5d
                  FROM theeyebeta.trading_calendar
                 WHERE is_trading_day
            ),
            history AS (
                SELECT
                    m.id,
                    m.as_of_date,
                    m.fed_funds_rate,
                    m.yield_10y,
                    m.yield_2y,
                    m.spread_2s10s,
                    m.dxy,
                    m.vix,
                    m.hy_oas_bps,
                    m.sp500_level,
                    m.nasdaq_level,
                    p21.fed_funds_rate AS ff_30d_ago,
                    p21.yield_10y AS y10_30d_ago,
                    p21.yield_2y AS y2_30d_ago,
                    p21.spread_2s10s AS spread_30d_ago,
                    p21.dxy AS dxy_30d_ago,
                    p21.hy_oas_bps AS hy_30d_ago,
                    p21.sp500_level AS sp500_30d_ago,
                    p21.nasdaq_level AS nasdaq_30d_ago,
                    p5.dxy AS dxy_5d_ago,
                    p5.vix AS vix_5d_ago,
                    p5.sp500_level AS sp500_5d_ago,
                    p5.nasdaq_level AS nasdaq_5d_ago,
                    MIN(m.vix) OVER (
                        ORDER BY m.as_of_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS vix_min_1y,
                    MAX(m.vix) OVER (
                        ORDER BY m.as_of_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS vix_max_1y
                  FROM theeyebeta.macro_regime_snapshots m
                  JOIN trading_days td ON td.calendar_date = m.as_of_date
                  LEFT JOIN theeyebeta.macro_regime_snapshots p21
                    ON p21.as_of_date = td.lag_21d
                  LEFT JOIN theeyebeta.macro_regime_snapshots p5
                    ON p5.as_of_date = td.lag_5d
            )
            UPDATE theeyebeta.macro_regime_snapshots r
            SET
                fed_funds_change_30d = h.fed_funds_rate - h.ff_30d_ago,
                yield_10y_change_30d = h.yield_10y - h.y10_30d_ago,
                yield_2y_change_30d = h.yield_2y - h.y2_30d_ago,
                spread_2s10s_change_30d = h.spread_2s10s - h.spread_30d_ago,
                dxy_change_5d = CASE WHEN h.dxy_5d_ago > 0
                    THEN ROUND((h.dxy - h.dxy_5d_ago) / h.dxy_5d_ago * 100, 4) END,
                dxy_change_30d = CASE WHEN h.dxy_30d_ago > 0
                    THEN ROUND((h.dxy - h.dxy_30d_ago) / h.dxy_30d_ago * 100, 4) END,
                vix_change_5d = h.vix - h.vix_5d_ago,
                vix_pct_rank_1y = CASE WHEN (h.vix_max_1y - h.vix_min_1y) > 0
                    THEN ROUND(
                        (h.vix - h.vix_min_1y) / (h.vix_max_1y - h.vix_min_1y) * 100,
                    2) END,
                hy_oas_change_30d = h.hy_oas_bps - h.hy_30d_ago,
                sp500_change_5d_pct = CASE WHEN h.sp500_5d_ago > 0
                    THEN ROUND((h.sp500_level - h.sp500_5d_ago) / h.sp500_5d_ago * 100, 4) END,
                sp500_change_30d_pct = CASE WHEN h.sp500_30d_ago > 0
                    THEN ROUND((h.sp500_level - h.sp500_30d_ago) / h.sp500_30d_ago * 100, 4) END,
                nasdaq_change_5d_pct = CASE WHEN h.nasdaq_5d_ago > 0
                    THEN ROUND((h.nasdaq_level - h.nasdaq_5d_ago) / h.nasdaq_5d_ago * 100, 4) END,
                nasdaq_change_30d_pct = CASE WHEN h.nasdaq_30d_ago > 0
                    THEN ROUND((h.nasdaq_level - h.nasdaq_30d_ago) / h.nasdaq_30d_ago * 100, 4) END,
                cpi_surprise = NULL
            FROM history h
            WHERE r.id = h.id
            """,
        )

    async def _compute_dry_run_row(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        raw: dict[str, float | None],
    ) -> asyncpg.Record:
        row = await conn.fetchrow(
            """
            WITH source AS (
                SELECT *
                  FROM theeyebeta.macro_regime_snapshots
                 WHERE as_of_date <> $1
                UNION ALL
                SELECT
                    NULL::bigint AS id,
                    $1::date AS as_of_date,
                    $2::numeric AS fed_funds_rate,
                    $3::numeric AS yield_10y,
                    $4::numeric AS yield_2y,
                    $5::numeric AS spread_2s10s,
                    $6::numeric AS vix,
                    $7::numeric AS dxy,
                    $8::numeric AS hy_oas_bps,
                    'unknown'::varchar AS rate_environment,
                    'unknown'::varchar AS yield_curve,
                    'unknown'::varchar AS credit_environment,
                    'unknown'::varchar AS volatility_regime,
                    'unknown'::varchar AS dollar_regime,
                    '{}'::jsonb AS style_tilts,
                    'fred+yfinance'::varchar AS data_source,
                    now() AS computed_at,
                    $9::numeric AS sp500_level,
                    $10::numeric AS sp500_change_pct,
                    $11::numeric AS nasdaq_level,
                    $12::numeric AS nasdaq_change_pct,
                    $13::numeric AS cpi,
                    $14::numeric AS gdp,
                    NULL::numeric AS fed_funds_change_30d,
                    NULL::numeric AS yield_10y_change_30d,
                    NULL::numeric AS yield_2y_change_30d,
                    NULL::numeric AS spread_2s10s_change_30d,
                    NULL::numeric AS dxy_change_5d,
                    NULL::numeric AS dxy_change_30d,
                    NULL::numeric AS vix_change_5d,
                    NULL::numeric AS vix_pct_rank_1y,
                    NULL::numeric AS hy_oas_change_30d,
                    NULL::numeric AS sp500_change_5d_pct,
                    NULL::numeric AS sp500_change_30d_pct,
                    NULL::numeric AS nasdaq_change_5d_pct,
                    NULL::numeric AS nasdaq_change_30d_pct,
                    NULL::numeric AS cpi_surprise,
                    NULL::numeric AS cpi_yoy_pct,
                    NULL::numeric AS gdp_qoq_pct
            ),
            history AS (
                SELECT
                    source.*,
                    LAG(fed_funds_rate, 21) OVER (ORDER BY as_of_date) AS ff_30d_ago,
                    LAG(yield_10y, 21) OVER (ORDER BY as_of_date) AS y10_30d_ago,
                    LAG(yield_2y, 21) OVER (ORDER BY as_of_date) AS y2_30d_ago,
                    LAG(spread_2s10s, 21) OVER (ORDER BY as_of_date) AS spread_30d_ago,
                    LAG(dxy, 21) OVER (ORDER BY as_of_date) AS dxy_30d_ago,
                    LAG(hy_oas_bps, 21) OVER (ORDER BY as_of_date) AS hy_30d_ago,
                    LAG(sp500_level, 21) OVER (ORDER BY as_of_date) AS sp500_30d_ago,
                    LAG(nasdaq_level, 21) OVER (ORDER BY as_of_date) AS nasdaq_30d_ago,
                    LAG(dxy, 5) OVER (ORDER BY as_of_date) AS dxy_5d_ago,
                    LAG(vix, 5) OVER (ORDER BY as_of_date) AS vix_5d_ago,
                    LAG(sp500_level, 5) OVER (ORDER BY as_of_date) AS sp500_5d_ago,
                    LAG(nasdaq_level, 5) OVER (ORDER BY as_of_date) AS nasdaq_5d_ago,
                    MIN(vix) OVER (
                        ORDER BY as_of_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS vix_min_1y,
                    MAX(vix) OVER (
                        ORDER BY as_of_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS vix_max_1y
                FROM source
            )
            SELECT
                id,
                as_of_date,
                fed_funds_rate,
                yield_10y,
                yield_2y,
                spread_2s10s,
                vix,
                dxy,
                hy_oas_bps,
                rate_environment,
                yield_curve,
                credit_environment,
                volatility_regime,
                dollar_regime,
                style_tilts,
                data_source,
                computed_at,
                sp500_level,
                sp500_change_pct,
                nasdaq_level,
                nasdaq_change_pct,
                cpi,
                gdp,
                fed_funds_rate - ff_30d_ago AS fed_funds_change_30d,
                yield_10y - y10_30d_ago AS yield_10y_change_30d,
                yield_2y - y2_30d_ago AS yield_2y_change_30d,
                spread_2s10s - spread_30d_ago AS spread_2s10s_change_30d,
                CASE WHEN dxy_5d_ago > 0
                    THEN ROUND((dxy - dxy_5d_ago) / dxy_5d_ago * 100, 4) END AS dxy_change_5d,
                CASE WHEN dxy_30d_ago > 0
                    THEN ROUND((dxy - dxy_30d_ago) / dxy_30d_ago * 100, 4) END AS dxy_change_30d,
                vix - vix_5d_ago AS vix_change_5d,
                CASE WHEN (vix_max_1y - vix_min_1y) > 0
                    THEN ROUND((vix - vix_min_1y) / (vix_max_1y - vix_min_1y) * 100, 2) END
                    AS vix_pct_rank_1y,
                hy_oas_bps - hy_30d_ago AS hy_oas_change_30d,
                CASE WHEN sp500_5d_ago > 0
                    THEN ROUND((sp500_level - sp500_5d_ago) / sp500_5d_ago * 100, 4) END
                    AS sp500_change_5d_pct,
                CASE WHEN sp500_30d_ago > 0
                    THEN ROUND((sp500_level - sp500_30d_ago) / sp500_30d_ago * 100, 4) END
                    AS sp500_change_30d_pct,
                CASE WHEN nasdaq_5d_ago > 0
                    THEN ROUND((nasdaq_level - nasdaq_5d_ago) / nasdaq_5d_ago * 100, 4) END
                    AS nasdaq_change_5d_pct,
                CASE WHEN nasdaq_30d_ago > 0
                    THEN ROUND((nasdaq_level - nasdaq_30d_ago) / nasdaq_30d_ago * 100, 4) END
                    AS nasdaq_change_30d_pct,
                NULL::numeric AS cpi_surprise,
                NULL::numeric AS cpi_yoy_pct,
                NULL::numeric AS gdp_qoq_pct
            FROM history
            WHERE as_of_date = $1
            """,
            trade_date,
            _as_decimal(raw["fed_funds_rate"]),
            _as_decimal(raw["yield_10y"]),
            _as_decimal(raw["yield_2y"]),
            _as_decimal(raw["spread_2s10s"]),
            _as_decimal(raw["vix"]),
            _as_decimal(raw["dxy"]),
            _as_decimal(raw["hy_oas_bps"]),
            _as_decimal(raw["sp500_level"]),
            _as_decimal(raw["sp500_change_pct"]),
            _as_decimal(raw["nasdaq_level"]),
            _as_decimal(raw["nasdaq_change_pct"]),
            _as_decimal(raw["cpi"]),
            _as_decimal(raw["gdp"]),
        )
        if row is None:
            raise RuntimeError("Dry-run macro row computation returned no row")
        return row

    async def _fetch_canonical(self, conn: asyncpg.Connection, trade_date: date) -> asyncpg.Record:
        row = await conn.fetchrow(
            """
            SELECT *
              FROM theeyebeta.macro_regime_snapshots
             WHERE as_of_date = $1
             LIMIT 1
            """,
            trade_date,
        )
        if row is None:
            raise RuntimeError(f"No canonical macro row for {trade_date}")
        return row

    def _classify_row(self, row: dict[str, object]) -> dict[str, object]:
        rate_environment = classify_rate_environment(_to_float(row.get("fed_funds_change_30d")))
        yield_curve = classify_yield_curve(_to_float(row.get("spread_2s10s")))
        credit_environment = classify_credit_environment(_to_float(row.get("hy_oas_bps")))
        volatility_regime = classify_volatility_regime(_to_float(row.get("vix")))
        dollar_regime = classify_dollar_regime(_to_float(row.get("dxy_change_30d")))
        row["rate_environment"] = rate_environment
        row["yield_curve"] = yield_curve
        row["credit_environment"] = credit_environment
        row["volatility_regime"] = volatility_regime
        row["dollar_regime"] = dollar_regime
        row["style_tilts"] = compute_style_tilts(
            rate_environment,
            yield_curve,
            credit_environment,
            volatility_regime,
            dollar_regime,
        )
        return row

    async def _update_canonical_classification(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        classified: dict[str, object],
    ) -> None:
        await conn.execute(
            """
            UPDATE theeyebeta.macro_regime_snapshots
               SET rate_environment = $2,
                   yield_curve = $3,
                   credit_environment = $4,
                   volatility_regime = $5,
                   dollar_regime = $6,
                   style_tilts = $7::jsonb
             WHERE as_of_date = $1
            """,
            trade_date,
            classified["rate_environment"],
            classified["yield_curve"],
            classified["credit_environment"],
            classified["volatility_regime"],
            classified["dollar_regime"],
            json.dumps(classified["style_tilts"]),
        )


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    worker = MacroRegimeWorker()
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=1,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MacroRegimeWorker")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; default today")
    parser.add_argument("--run-type", default="manual", choices=["manual", "scheduled", "recovery"])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
