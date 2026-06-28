"""Fixed-income regime worker.

CLI examples:
    python -m workers.fixed_income.pipeline_worker --date 2026-06-10
    python -m workers.fixed_income.pipeline_worker --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import yfinance as yf

from workers.base_worker import BaseWorker, WorkerResult
from workers.fixed_income.calculations import (
    calculate_bond_environment_score,
    classify_bond_environment,
    classify_credit_regime,
    classify_curve_regime,
    classify_rate_regime,
    generate_fixed_income_signals,
)
from workers.fixed_income.series import ETF_PROXIES, ETF_PROXY_SYMBOLS, FRED_SERIES
from workers.fred_client import FredClient, FredObservation

COUNTRY = "US"
CURRENCY = "USD"
SOURCE = "fred+yfinance"

METRIC_COLUMNS = (
    "date",
    "country",
    "currency",
    "y_1mo",
    "y_3mo",
    "y_6mo",
    "y_1y",
    "y_2y",
    "y_5y",
    "y_10y",
    "y_20y",
    "y_30y",
    "spread_10y_2y",
    "spread_10y_3m",
    "spread_30y_5y",
    "real_yield_10y",
    "high_yield_spread",
    "ig_corp_spread",
    "y_2y_change_5d",
    "y_10y_change_5d",
    "y_30y_change_5d",
    "y_2y_change_20d",
    "y_10y_change_20d",
    "y_30y_change_20d",
    "y_10y_volatility_20d",
    "curve_regime",
    "rate_regime",
    "credit_regime",
    "bond_environment_score",
    "bond_environment_label",
    "source",
)

NUMERIC_COLUMNS = {
    "y_1mo",
    "y_3mo",
    "y_6mo",
    "y_1y",
    "y_2y",
    "y_5y",
    "y_10y",
    "y_20y",
    "y_30y",
    "spread_10y_2y",
    "spread_10y_3m",
    "spread_30y_5y",
    "real_yield_10y",
    "high_yield_spread",
    "ig_corp_spread",
    "y_2y_change_5d",
    "y_10y_change_5d",
    "y_30y_change_5d",
    "y_2y_change_20d",
    "y_10y_change_20d",
    "y_30y_change_20d",
    "y_10y_volatility_20d",
}


def _as_decimal(value: float | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(round(float(value), 6)))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


class FixedIncomePipelineWorker(BaseWorker):
    """Ingest fixed-income sources and write derived curve metrics/signals."""

    worker_name = "FixedIncomePipelineWorker"
    worker_type = "macro"
    display_name = "Fixed Income Pipeline Worker"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        fred_client: FredClient | None = None,
        lookback_days: int = 420,
    ) -> None:
        super().__init__(database_url=database_url)
        self.fred = fred_client
        self.lookback_days = lookback_days

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

        start = trade_date - timedelta(days=self.lookback_days)
        fred_rows: list[dict[str, Any]] = []
        if not dry_run or self.fred is not None or os.environ.get("FRED_API_KEY"):
            observations_by_code = await self._fetch_observations(start=start, end=trade_date)
            fred_rows = self._build_indicator_rows(observations_by_code)

        if dry_run:
            metric = await self._compute_metric(conn, trade_date, extra_rows=fred_rows)
            signals = generate_fixed_income_signals(metric or {})
            summary = {
                "worker": self.worker_name,
                "trade_date": trade_date.isoformat(),
                "rows_would_write": {
                    "macro_indicators": len(fred_rows),
                    "fixed_income_curve_metrics": 1 if metric else 0,
                    "fixed_income_signals": len(signals),
                    "prices_daily": len(ETF_PROXIES),
                },
                "metric": metric,
                "signals": signals,
            }
            print(json.dumps(summary, indent=2, sort_keys=True, default=_json_default))
            return WorkerResult(
                records_written=0,
                records_expected=1,
                metadata={"dry_run": True, "rows_would_write": summary["rows_would_write"]},
            )

        async with conn.transaction():
            await self._upsert_macro_rows(conn, fred_rows)
            etf_rows_written = await self._ingest_etf_prices(conn, trade_date)
            metric = await self._compute_metric(conn, trade_date)
            if metric is None:
                raise RuntimeError(f"No fixed-income metric could be computed for {trade_date}")
            await self._upsert_metric(conn, metric)
            signals = generate_fixed_income_signals(metric)
            await self._replace_signals(conn, trade_date, signals)

        return WorkerResult(
            records_written=1 + len(signals) + etf_rows_written,
            records_expected=1,
            metadata={
                "date": trade_date.isoformat(),
                "curve_regime": metric["curve_regime"],
                "rate_regime": metric["rate_regime"],
                "credit_regime": metric["credit_regime"],
                "bond_environment_score": metric["bond_environment_score"],
                "bond_environment_label": metric["bond_environment_label"],
                "fred_rows_written": len(fred_rows),
                "signals_written": len(signals),
                "etf_price_rows_written": etf_rows_written,
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

    def _fred_client(self) -> FredClient:
        if self.fred is None:
            self.fred = FredClient()
        return self.fred

    async def _fetch_observations(
        self,
        *,
        start: date,
        end: date,
    ) -> dict[str, list[FredObservation]]:
        async def fetch_one(series_code: str) -> tuple[str, list[FredObservation]]:
            observations = await self._fred_client().observations(series_code, start=start, end=end)
            return series_code, observations

        pairs = await asyncio.gather(*(fetch_one(series_code) for series_code in FRED_SERIES))
        return dict(pairs)

    def _build_indicator_rows(
        self,
        observations_by_code: Mapping[str, Iterable[FredObservation]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for series_code, observations in observations_by_code.items():
            for observation in observations:
                rows.append(
                    {
                        "series_code": series_code,
                        "ts": observation.observed_at,
                        "value": observation.value,
                        "source": "fred:fixed_income",
                    }
                )
        return rows

    async def _upsert_macro_rows(
        self,
        conn: asyncpg.Connection,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            return
        await conn.executemany(
            """
            INSERT INTO theeyebeta.macro_indicators (series_code, ts, value, source)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (series_code, ts) DO UPDATE SET
                value = EXCLUDED.value,
                source = EXCLUDED.source
            """,
            [
                (
                    row["series_code"],
                    row["ts"],
                    _as_decimal(_to_float(row["value"])),
                    row["source"],
                )
                for row in rows
            ],
        )

    async def _compute_metric(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        extra_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        start = trade_date - timedelta(days=self.lookback_days)
        rows = await conn.fetch(
            """
            SELECT ts::date AS obs_date, series_code, value
              FROM theeyebeta.macro_indicators
             WHERE series_code = ANY($1::text[])
               AND ts::date >= $2
               AND ts::date <= $3
             ORDER BY ts::date, series_code
            """,
            list(FRED_SERIES),
            start,
            trade_date,
        )
        observations: dict[str, dict[date, float]] = {code: {} for code in FRED_SERIES}
        for row in rows:
            value = _to_float(row["value"])
            if value is not None:
                observations[str(row["series_code"])][row["obs_date"]] = value

        for row in extra_rows or []:
            value = _to_float(row["value"])
            if value is None:
                continue
            observed_date = row["ts"].date()
            observations.setdefault(str(row["series_code"]), {})[observed_date] = value

        if not any(observations.values()):
            return None

        trading_days = await self._trading_days(conn, start, trade_date)
        if not trading_days:
            return None

        by_code = {
            code: sorted(values.items(), key=lambda item: item[0])
            for code, values in observations.items()
        }
        positions = {code: 0 for code in by_code}
        latest: dict[str, float] = {}
        metrics: list[dict[str, Any]] = []
        for current_date in trading_days:
            for code, series in by_code.items():
                position = positions[code]
                while position < len(series) and series[position][0] <= current_date:
                    latest[code] = series[position][1]
                    position += 1
                positions[code] = position
            metric = self._metric_from_values(current_date, latest)
            if metric["y_10y"] is None and metric["y_2y"] is None:
                continue
            metrics.append(metric)

        if not metrics:
            return None
        self._finalize_metrics(metrics)
        return metrics[-1]

    async def _trading_days(
        self,
        conn: asyncpg.Connection,
        start: date,
        end: date,
    ) -> list[date]:
        rows = await conn.fetch(
            """
            SELECT calendar_date
              FROM theeyebeta.trading_calendar
             WHERE calendar_date >= $1
               AND calendar_date <= $2
               AND is_trading_day
             ORDER BY calendar_date
            """,
            start,
            end,
        )
        if rows:
            return [row["calendar_date"] for row in rows]

        days: list[date] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days

    def _metric_from_values(
        self,
        current_date: date,
        values: Mapping[str, float],
    ) -> dict[str, Any]:
        y_1mo = _to_float(values.get("DGS1MO"))
        y_3mo = _to_float(values.get("DGS3MO"))
        y_6mo = _to_float(values.get("DGS6MO"))
        y_1y = _to_float(values.get("DGS1"))
        y_2y = _to_float(values.get("DGS2"))
        y_5y = _to_float(values.get("DGS5"))
        y_10y = _to_float(values.get("DGS10"))
        y_20y = _to_float(values.get("DGS20"))
        y_30y = _to_float(values.get("DGS30"))

        spread_10y_2y = _to_float(values.get("T10Y2Y"))
        if spread_10y_2y is None and y_10y is not None and y_2y is not None:
            spread_10y_2y = y_10y - y_2y

        spread_10y_3m = _to_float(values.get("T10Y3M"))
        if spread_10y_3m is None and y_10y is not None and y_3mo is not None:
            spread_10y_3m = y_10y - y_3mo

        spread_30y_5y = None
        if y_30y is not None and y_5y is not None:
            spread_30y_5y = y_30y - y_5y

        return {
            "date": current_date,
            "country": COUNTRY,
            "currency": CURRENCY,
            "y_1mo": y_1mo,
            "y_3mo": y_3mo,
            "y_6mo": y_6mo,
            "y_1y": y_1y,
            "y_2y": y_2y,
            "y_5y": y_5y,
            "y_10y": y_10y,
            "y_20y": y_20y,
            "y_30y": y_30y,
            "spread_10y_2y": spread_10y_2y,
            "spread_10y_3m": spread_10y_3m,
            "spread_30y_5y": spread_30y_5y,
            "real_yield_10y": _to_float(values.get("DFII10")),
            "high_yield_spread": _to_float(values.get("BAMLH0A0HYM2")),
            "ig_corp_spread": _to_float(values.get("BAMLC0A0CM")),
            "y_2y_change_5d": None,
            "y_10y_change_5d": None,
            "y_30y_change_5d": None,
            "y_2y_change_20d": None,
            "y_10y_change_20d": None,
            "y_30y_change_20d": None,
            "y_10y_volatility_20d": None,
            "curve_regime": "unknown",
            "rate_regime": "unknown",
            "credit_regime": "unknown",
            "bond_environment_score": None,
            "bond_environment_label": "unknown",
            "source": SOURCE,
        }

    def _finalize_metrics(self, metrics: list[dict[str, Any]]) -> None:
        for index, metric in enumerate(metrics):
            for tenor in ("y_2y", "y_10y", "y_30y"):
                for lag in (5, 20):
                    key = f"{tenor}_change_{lag}d"
                    if index < lag:
                        metric[key] = None
                        continue
                    current = _to_float(metric.get(tenor))
                    previous = _to_float(metrics[index - lag].get(tenor))
                    metric[key] = (
                        None if current is None or previous is None else current - previous
                    )

            changes: list[float] = []
            start_index = max(1, index - 19)
            for change_index in range(start_index, index + 1):
                current = _to_float(metrics[change_index].get("y_10y"))
                previous = _to_float(metrics[change_index - 1].get("y_10y"))
                if current is not None and previous is not None:
                    changes.append(current - previous)
            metric["y_10y_volatility_20d"] = _stddev(changes)

            curve_regime = classify_curve_regime(
                _to_float(metric.get("spread_10y_2y")),
                _to_float(metric.get("spread_10y_3m")),
            )
            rate_regime = classify_rate_regime(
                _to_float(metric.get("y_10y_change_20d")),
                _to_float(metric.get("y_2y_change_20d")),
            )
            credit_regime = classify_credit_regime(_to_float(metric.get("high_yield_spread")))
            score = calculate_bond_environment_score(
                curve_regime=curve_regime,
                rate_regime=rate_regime,
                real_yield_10y=_to_float(metric.get("real_yield_10y")),
                credit_regime=credit_regime,
            )
            metric["curve_regime"] = curve_regime
            metric["rate_regime"] = rate_regime
            metric["credit_regime"] = credit_regime
            metric["bond_environment_score"] = score
            metric["bond_environment_label"] = classify_bond_environment(score)

    async def _upsert_metric(self, conn: asyncpg.Connection, metric: Mapping[str, Any]) -> None:
        placeholders = ", ".join(f"${index}" for index in range(1, len(METRIC_COLUMNS) + 1))
        update_sql = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in METRIC_COLUMNS
            if column not in {"date", "country"}
        )
        values: list[Any] = []
        for column in METRIC_COLUMNS:
            value = metric.get(column)
            values.append(_as_decimal(_to_float(value)) if column in NUMERIC_COLUMNS else value)
        await conn.execute(
            f"""
            INSERT INTO theeyebeta.fixed_income_curve_metrics
                ({", ".join(METRIC_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (date, country) DO UPDATE SET
                {update_sql},
                updated_at = now()
            """,  # noqa: S608
            *values,
        )

    async def _replace_signals(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        signals: list[dict[str, Any]],
    ) -> None:
        await conn.execute(
            """
            DELETE FROM theeyebeta.fixed_income_signals
             WHERE date = $1
               AND country = $2
            """,
            trade_date,
            COUNTRY,
        )
        if not signals:
            return
        await conn.executemany(
            """
            INSERT INTO theeyebeta.fixed_income_signals
                (date, country, signal_name, signal_value, signal_strength,
                 signal_direction, interpretation)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (date, country, signal_name) DO UPDATE SET
                signal_value = EXCLUDED.signal_value,
                signal_strength = EXCLUDED.signal_strength,
                signal_direction = EXCLUDED.signal_direction,
                interpretation = EXCLUDED.interpretation,
                updated_at = now()
            """,
            [
                (
                    trade_date,
                    COUNTRY,
                    signal["signal_name"],
                    _as_decimal(_to_float(signal.get("value"))),
                    signal["strength"],
                    signal["direction"],
                    signal["interpretation"],
                )
                for signal in signals
            ],
        )

    async def _ingest_etf_prices(self, conn: asyncpg.Connection, trade_date: date) -> int:
        instruments = await self._etf_instruments(conn)
        rows: list[tuple[Any, ...]] = []
        for proxy in ETF_PROXIES:
            instrument_id = instruments.get(proxy.symbol)
            if instrument_id is None:
                continue
            bar = await self._fetch_yfinance_bar(proxy.symbol, trade_date)
            if bar is None:
                continue
            rows.append(
                (
                    instrument_id,
                    datetime.combine(bar["date"], time.min, tzinfo=UTC),
                    _as_decimal(bar["open"]),
                    _as_decimal(bar["high"]),
                    _as_decimal(bar["low"]),
                    _as_decimal(bar["close"]),
                    _as_decimal(bar["adj_close"]),
                    int(bar["volume"] or 0),
                    "yfinance:fixed_income_proxy",
                )
            )

        if not rows:
            return 0
        await conn.executemany(
            """
            INSERT INTO theeyebeta.prices_daily
                (instrument_id, ts, open, high, low, close, adj_close, volume, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (instrument_id, ts) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                adj_close = EXCLUDED.adj_close,
                volume = EXCLUDED.volume,
                source = EXCLUDED.source,
                ingested_at = now()
            """,
            rows,
        )
        return len(rows)

    async def _etf_instruments(self, conn: asyncpg.Connection) -> dict[str, int]:
        rows = await conn.fetch(
            """
            SELECT i.symbol, i.id
              FROM theeyebeta.instruments i
              JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
             WHERE i.symbol = ANY($1::text[])
               AND i.asset_class = 'etf'
               AND i.active
            """,
            list(ETF_PROXY_SYMBOLS),
        )
        return {str(row["symbol"]): int(row["id"]) for row in rows}

    async def _fetch_yfinance_bar(self, ticker: str, trade_date: date) -> dict[str, Any] | None:
        def fetch() -> dict[str, Any] | None:
            start = trade_date - timedelta(days=14)
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
                return None
            if getattr(frame.columns, "nlevels", 1) > 1:
                for level in range(frame.columns.nlevels):
                    if ticker in frame.columns.get_level_values(level):
                        frame = frame.xs(ticker, axis=1, level=level, drop_level=True)
                        break
            eligible = frame[frame.index.date <= trade_date]
            if eligible.empty:
                return None
            latest = eligible.iloc[-1]
            close = _to_float(latest.get("Close"))
            if close is None:
                return None
            return {
                "date": latest.name.date(),
                "open": _to_float(latest.get("Open")) or close,
                "high": _to_float(latest.get("High")) or close,
                "low": _to_float(latest.get("Low")) or close,
                "close": close,
                "adj_close": _to_float(latest.get("Adj Close")) or close,
                "volume": int(_to_float(latest.get("Volume")) or 0),
            }

        return await asyncio.to_thread(fetch)


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    worker = FixedIncomePipelineWorker()
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=1,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FixedIncomePipelineWorker")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; default today")
    parser.add_argument("--run-type", default="manual", choices=["manual", "scheduled", "recovery"])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
