"""Macro indicator ingestion worker.

CLI examples:
    python -m workers.macro_ingestion_worker --date 2026-06-10
    python -m workers.macro_ingestion_worker --dry-run
    python -m workers.macro_ingestion_worker --set-ism --series ISM_MFG \
        --value 52.3 --date 2026-06-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg

from workers.base_worker import BaseWorker, WorkerResult, worker_database_url
from workers.fred_client import FredClient, FredObservation
from workers.macro_calculations import compute_month_over_month_diff, compute_yoy_percent

FRED_SERIES = {
    "NONFARM_PAYROLLS_LEVEL": "PAYEMS",
    "UNEMPLOYMENT_RATE": "UNRATE",
    "PCE_CORE_INDEX": "PCEPILFE",
    "BREAKEVEN_5Y": "T5YIE",
    "BREAKEVEN_10Y": "T10YIE",
    "IG_OAS": "BAMLC0A0CM",
    "CPIAUCSL": "CPIAUCSL",
    "GDPC1": "GDPC1",
}

ISM_SERIES = {
    "ISM_MFG": {"source": "manual"},
    "ISM_SVC": {"source": "manual"},
}

_BPS_SERIES_CODES = {"IG_OAS"}


def _as_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


class MacroIngestionWorker(BaseWorker):
    """Fetch corrected macro series and store them in ``theeyebeta.macro_indicators``."""

    worker_name = "MacroIngestionWorker"
    worker_type = "macro"
    display_name = "Macro Ingestion Worker"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        fred_client: FredClient | None = None,
        lookback_days: int = 800,
    ) -> None:
        super().__init__(database_url=database_url)
        self.fred = fred_client or FredClient()
        self.lookback_days = lookback_days

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        start = trade_date - timedelta(days=self.lookback_days)
        observations_by_code = await self._fetch_observations(start=start, end=trade_date)
        rows = self._build_indicator_rows(observations_by_code)

        if dry_run:
            print(
                json.dumps(
                    {
                        "worker": self.worker_name,
                        "trade_date": trade_date.isoformat(),
                        "rows_would_write": len(rows),
                        "series": sorted({row["series_code"] for row in rows}),
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
            return WorkerResult(
                records_written=0,
                records_expected=len(FRED_SERIES),
                metadata={"dry_run": True, "rows_would_write": len(rows)},
            )

        async with conn.transaction():
            await self._upsert_macro_rows(conn, rows)
            stale_ism = await self._audit_stale_ism(conn, trade_date)

        return WorkerResult(
            records_written=len(rows),
            records_expected=len(FRED_SERIES),
            metadata={
                "series": sorted({row["series_code"] for row in rows}),
                "stale_ism_series": stale_ism,
            },
        )

    async def _fetch_observations(
        self,
        *,
        start: date,
        end: date,
    ) -> dict[str, list[FredObservation]]:
        async def fetch_one(series_code: str, fred_id: str) -> tuple[str, list[FredObservation]]:
            return series_code, await self.fred.observations(fred_id, start=start, end=end)

        pairs = await asyncio.gather(
            *(fetch_one(series_code, fred_id) for series_code, fred_id in FRED_SERIES.items()),
        )
        return dict(pairs)

    def _build_indicator_rows(
        self,
        observations_by_code: dict[str, list[FredObservation]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for series_code, observations in observations_by_code.items():
            for observation in observations:
                value = (
                    observation.value * 100.0
                    if series_code in _BPS_SERIES_CODES
                    else observation.value
                )
                rows.append(
                    {
                        "series_code": series_code,
                        "ts": observation.observed_at,
                        "value": value,
                        "source": "fred",
                    },
                )

        payroll_points = [
            (obs.observed_date, obs.value)
            for obs in observations_by_code.get("NONFARM_PAYROLLS_LEVEL", [])
        ]
        for observed_date, value in compute_month_over_month_diff(payroll_points):
            rows.append(
                {
                    "series_code": "NONFARM_PAYROLLS",
                    "ts": datetime.combine(observed_date, time.min, tzinfo=UTC),
                    "value": value,
                    "source": "fred:derived",
                },
            )

        pce_points = [
            (obs.observed_date, obs.value) for obs in observations_by_code.get("PCE_CORE_INDEX", [])
        ]
        for observed_date, value in compute_yoy_percent(pce_points):
            rows.append(
                {
                    "series_code": "PCE_CORE",
                    "ts": datetime.combine(observed_date, time.min, tzinfo=UTC),
                    "value": value,
                    "source": "fred:derived",
                },
            )
        return rows

    async def _upsert_macro_rows(
        self,
        conn: asyncpg.Connection,
        rows: list[dict[str, Any]],
    ) -> None:
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
                    _as_decimal(float(row["value"])),
                    row["source"],
                )
                for row in rows
            ],
        )

    async def _audit_stale_ism(self, conn: asyncpg.Connection, trade_date: date) -> list[str]:
        stale: list[str] = []
        for series_code in ISM_SERIES:
            latest_ts = await conn.fetchval(
                """
                SELECT MAX(ts)::date
                  FROM theeyebeta.macro_indicators
                 WHERE series_code = $1
                """,
                series_code,
            )
            is_fresh = latest_ts is not None and latest_ts >= trade_date - timedelta(days=40)
            if is_fresh:
                continue
            stale.append(series_code)
            expected_start = datetime.combine(trade_date, time.min, tzinfo=UTC)
            expected_end = datetime.combine(trade_date, time.max, tzinfo=UTC)
            gap_id = await conn.fetchval(
                """
                INSERT INTO public.audit_data_gaps
                    (dataset_type, trade_date, expected_start, expected_end,
                     expected_count, actual_count, gap_start, gap_end,
                     severity, remediation_state, remediation_notes, metadata)
                VALUES (
                    'indicators_technical',
                    $1,
                    $2,
                    $3,
                    1,
                    0,
                    $2,
                    $3,
                    'WARN',
                    'OPEN',
                    'Manual ISM PMI entry required',
                    $4::jsonb
                )
                RETURNING gap_id
                """,
                trade_date,
                expected_start,
                expected_end,
                json.dumps(
                    {
                        "series_code": series_code,
                        "latest_ts": latest_ts.isoformat() if latest_ts else None,
                        "stale_after_days": 40,
                    },
                ),
            )
            await conn.execute(
                """
                INSERT INTO public.audit_alerts
                    (alert_type, severity, trade_date, worker_name, gap_id, run_id,
                     title, message, metadata)
                VALUES (
                    'DATA_GAP',
                    'WARN',
                    $1,
                    $2,
                    $3,
                    $4,
                    'ISM PMI series stale — manual entry required',
                    $5,
                    $6::jsonb
                )
                """,
                trade_date,
                self.worker_name,
                gap_id,
                self.run_id,
                f"{series_code} has no observation within 40 days of {trade_date}.",
                json.dumps({"series_code": series_code}),
            )
        return stale


async def set_ism_value(
    *,
    series_code: str,
    value: float,
    observed_date: date,
    database_url: str | None = None,
) -> None:
    """Manual helper to store an ISM PMI print."""
    if series_code not in ISM_SERIES:
        msg = f"series must be one of {', '.join(sorted(ISM_SERIES))}"
        raise ValueError(msg)
    conn = await asyncpg.connect((database_url or worker_database_url()).replace("+psycopg", ""))
    try:
        await conn.execute(
            """
            INSERT INTO theeyebeta.macro_indicators (series_code, ts, value, source)
            VALUES ($1, $2, $3, 'manual')
            ON CONFLICT (series_code, ts) DO UPDATE SET
                value = EXCLUDED.value,
                source = EXCLUDED.source
            """,
            series_code,
            datetime.combine(observed_date, time.min, tzinfo=UTC),
            _as_decimal(value),
        )
    finally:
        await conn.close()


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    if args.set_ism:
        if args.series is None or args.value is None:
            raise SystemExit("--set-ism requires --series and --value")
        await set_ism_value(
            series_code=args.series,
            value=float(args.value),
            observed_date=target_date,
        )
        print(f"Stored {args.series}={args.value} for {target_date}")
        return

    worker = MacroIngestionWorker()
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=len(FRED_SERIES),
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MacroIngestionWorker")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; default today")
    parser.add_argument("--run-type", default="manual", choices=["manual", "scheduled", "recovery"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--set-ism", action="store_true", help="Store a manual ISM PMI value")
    parser.add_argument("--series", choices=sorted(ISM_SERIES))
    parser.add_argument("--value", type=float)
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
