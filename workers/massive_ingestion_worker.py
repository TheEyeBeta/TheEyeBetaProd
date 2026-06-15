"""Canonical daily price ingestion via Massive.com grouped-daily with fallbacks.

CLI examples:
    python -m workers.massive_ingestion_worker --dry-run
    python -m workers.massive_ingestion_worker --date 2026-06-09 --run-type manual
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.massive_providers import (
    COVERAGE_FAIL_THRESHOLD,
    FINNHUB_FALLBACK_MAX,
    YFINANCE_FALLBACK_MAX,
    DailyBar,
    FinnhubClient,
    MassiveClient,
    UniverseInstrument,
    bar_to_row,
    bars_still_missing,
    classify_coverage,
    fetch_yfinance_bar,
    parse_massive_grouped,
    pick_spot_check_symbols,
    provider_chain_plan,
    validate_bar,
)

log = structlog.get_logger()


class CoverageError(RuntimeError):
    """Raised when canonical coverage falls below the hard fail threshold."""

    def __init__(self, missing_symbols: list[str], written: int, expected: int) -> None:
        self.missing_symbols = missing_symbols
        self.written = written
        self.expected = expected
        ratio = written / expected if expected else 0.0
        super().__init__(
            f"Coverage {ratio:.1%} below {COVERAGE_FAIL_THRESHOLD:.0%}; "
            f"missing={missing_symbols[:50]}",
        )


class MassiveDailyIngestionWorker(BaseWorker):
    """Ingest canonical theeyebeta.prices_daily from Massive grouped-daily."""

    worker_name = "MassiveDailyIngestionWorker"
    worker_type = "canonical_prices"
    display_name = "Massive Daily Ingestion"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        massive_client: MassiveClient | None = None,
        finnhub_client: FinnhubClient | None = None,
        target_symbol: str | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
        self._massive = massive_client
        self._finnhub = finnhub_client
        self._target_symbol = target_symbol.upper() if target_symbol else None

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)
        if target is None:
            payload = {
                "worker": self.worker_name,
                "trade_date": trade_date.isoformat(),
                "status": "skipped",
                "note": "non-trading day",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={"note": "non-trading day", "skipped": True},
            )

        universe = await load_universe(conn)
        if self._target_symbol is not None:
            universe = [inst for inst in universe if inst.symbol == self._target_symbol]
            if not universe:
                raise ValueError(
                    f"Symbol {self._target_symbol!r} not found in active canonical universe"
                )
        expected = len(universe)
        symbol_map = {inst.symbol: inst for inst in universe}
        if dry_run and not os.environ.get("MASSIVE_API_KEY") and self._massive is None:
            payload = build_static_dry_run_payload(universe=universe, trade_date=target)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return WorkerResult(
                records_written=0,
                records_expected=expected,
                metadata=payload,
            )

        prev_closes = await load_prev_closes(conn, universe, target)

        massive = self._massive or MassiveClient()
        finnhub = self._finnhub or FinnhubClient()
        own_massive = self._massive is None
        own_finnhub = self._finnhub is None

        try:
            plan = await build_ingestion_plan(
                universe=universe,
                symbol_map=symbol_map,
                trade_date=target,
                prev_closes=prev_closes,
                conn=conn,
                massive=massive,
                finnhub=finnhub,
            )
        finally:
            if own_massive:
                await massive.aclose()
            if own_finnhub:
                await finnhub.aclose()

        if dry_run:
            print(json.dumps(plan["dry_run_payload"], indent=2, sort_keys=True))
            return WorkerResult(
                records_written=0,
                records_expected=expected,
                metadata=plan["dry_run_payload"],
            )

        written_bars: dict[str, DailyBar] = plan["bars_to_write"]
        missing_symbols = plan["missing_symbols"]
        written_count = len(written_bars)
        outcome = classify_coverage(written_count, expected)

        async with conn.transaction():
            for bar in written_bars.values():
                await upsert_price(conn, bar)

            if outcome == "fail":
                await create_coverage_alert(
                    conn,
                    worker_name=self.worker_name,
                    run_id=self.run_id,
                    trade_date=target,
                    severity="CRITICAL",
                    missing_symbols=missing_symbols,
                    written=written_count,
                    expected=expected,
                )
                raise CoverageError(missing_symbols, written_count, expected)

            if outcome == "warn":
                await create_coverage_alert(
                    conn,
                    worker_name=self.worker_name,
                    run_id=self.run_id,
                    trade_date=target,
                    severity="WARN",
                    missing_symbols=missing_symbols,
                    written=written_count,
                    expected=expected,
                )

            for note in plan.get("spot_check_warnings", []):
                await create_provider_divergence_alert(
                    conn,
                    worker_name=self.worker_name,
                    run_id=self.run_id,
                    trade_date=target,
                    message=note,
                )

        sources: dict[str, int] = {}
        for bar in written_bars.values():
            sources[bar.source] = sources.get(bar.source, 0) + 1

        return WorkerResult(
            records_written=written_count,
            records_expected=expected,
            metadata={
                "trade_date": target.isoformat(),
                "coverage_ratio": written_count / expected if expected else 0.0,
                "coverage_outcome": outcome,
                "missing_symbols": missing_symbols,
                "source_counts": sources,
                "spot_check_warnings": plan.get("spot_check_warnings", []),
            },
        )


def build_static_dry_run_payload(
    *,
    universe: list[UniverseInstrument],
    trade_date: date,
) -> dict[str, Any]:
    """Build a DB-only dry-run plan when provider keys are not configured."""
    symbols = [inst.symbol for inst in universe]
    return {
        "worker": MassiveDailyIngestionWorker.worker_name,
        "trade_date": trade_date.isoformat(),
        "active_universe": len(universe),
        "primary_provider": "massive",
        "provider_chain": ["massive", "finnhub", "yfinance"],
        "planned_writes": len(universe),
        "planned_coverage": 1.0,
        "symbols_sample": symbols[:20],
        "note": (
            "Static dry-run plan (MASSIVE_API_KEY not set). "
            "Live fetch dry-run requires provider keys in .env."
        ),
        "dry_run": True,
    }


async def resolve_target_trade_date(conn: asyncpg.Connection, as_of: date) -> date | None:
    """Return ``as_of`` when it is a trading day, else ``None``."""
    value = await conn.fetchval(
        """
        SELECT is_trading_day
          FROM theeyebeta.trading_calendar
         WHERE calendar_date = $1
         LIMIT 1
        """,
        as_of,
    )
    if value is None:
        return as_of if as_of.weekday() < 5 else None
    return as_of if bool(value) else None


async def load_universe(conn: asyncpg.Connection) -> list[UniverseInstrument]:
    """Load active mapped instruments for canonical ingestion."""
    rows = await conn.fetch(
        """
        SELECT i.id AS instrument_id,
               m.public_ticker_id AS ticker_id,
               i.symbol,
               e.code AS exchange_code
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
         WHERE i.active
         ORDER BY i.symbol
        """,
    )
    return [
        UniverseInstrument(
            instrument_id=int(row["instrument_id"]),
            ticker_id=int(row["ticker_id"]),
            symbol=str(row["symbol"]),
            exchange_code=str(row["exchange_code"]),
        )
        for row in rows
    ]


async def load_prev_closes(
    conn: asyncpg.Connection,
    universe: list[UniverseInstrument],
    trade_date: date,
) -> dict[int, float]:
    """Load prior-session closes for sanity gates."""
    ref_date = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )
    if ref_date is None:
        return {}
    instrument_ids = [inst.instrument_id for inst in universe]
    rows = await conn.fetch(
        """
        SELECT m.public_ticker_id AS ticker_id, p.close::float AS close
          FROM theeyebeta.prices_daily p
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = p.instrument_id
         WHERE p.ts::date = $1
           AND p.instrument_id = ANY($2::bigint[])
        """,
        ref_date,
        instrument_ids,
    )
    return {int(row["ticker_id"]): float(row["close"]) for row in rows}


async def has_corporate_action(
    conn: asyncpg.Connection,
    instrument_id: int,
    trade_date: date,
) -> bool:
    """Return whether a corporate action exists near ``trade_date``."""
    value = await conn.fetchval(
        """
        SELECT 1
          FROM theeyebeta.corporate_actions
         WHERE instrument_id = $1
           AND ex_date BETWEEN ($2::date - 3) AND ($2::date + 3)
         LIMIT 1
        """,
        instrument_id,
        trade_date,
    )
    return value is not None


async def build_ingestion_plan(
    *,
    universe: list[UniverseInstrument],
    symbol_map: dict[str, UniverseInstrument],
    trade_date: date,
    prev_closes: dict[int, float],
    conn: asyncpg.Connection,
    massive: MassiveClient,
    finnhub: FinnhubClient,
) -> dict[str, Any]:
    """Fetch providers, validate bars, and assemble the write plan."""
    grouped = await massive.grouped_daily(trade_date)
    massive_bars = parse_massive_grouped(grouped, symbol_map=symbol_map, trade_date=trade_date)

    collected: dict[str, DailyBar] = {}
    rejected: list[str] = []
    provider_plan = provider_chain_plan(universe, massive_bars)
    finnhub_attempts = 0
    yfinance_attempts = 0
    fallback_budget_exhausted = 0

    for inst, primary in provider_plan:
        if primary == "massive":
            bar = massive_bars[inst.symbol]
            bar.instrument_id = inst.instrument_id
        else:
            bar = None

        if bar is not None:
            reason = await validate_with_db(
                conn,
                inst,
                bar,
                prev_closes.get(inst.ticker_id),
            )
            if reason:
                rejected.append(reason)
                bar = None
            else:
                collected[inst.symbol] = bar
                continue

        if primary != "massive" or bar is None:
            finn = None
            if finnhub_attempts < FINNHUB_FALLBACK_MAX:
                finnhub_attempts += 1
                finn = await finnhub.daily_bar(inst.symbol, trade_date)
            else:
                fallback_budget_exhausted += 1
            if finn is not None:
                finn.instrument_id = inst.instrument_id
                reason = await validate_with_db(
                    conn,
                    inst,
                    finn,
                    prev_closes.get(inst.ticker_id),
                )
                if reason:
                    rejected.append(reason)
                else:
                    collected[inst.symbol] = finn
                    continue

            if yfinance_attempts < YFINANCE_FALLBACK_MAX:
                yfinance_attempts += 1
                try:
                    yf_bar = await asyncio.to_thread(fetch_yfinance_bar, inst, trade_date)
                except Exception as exc:  # noqa: BLE001 — provider failure is non-fatal
                    log.warning("yfinance_fallback_failed", symbol=inst.symbol, error=str(exc))
                    yf_bar = None
            else:
                fallback_budget_exhausted += 1
                yf_bar = None
            if yf_bar is not None:
                reason = await validate_with_db(
                    conn,
                    inst,
                    yf_bar,
                    prev_closes.get(inst.ticker_id),
                )
                if reason:
                    rejected.append(reason)
                else:
                    collected[inst.symbol] = yf_bar

    missing = [inst.symbol for inst in bars_still_missing(universe, collected)]
    spot_warnings = await run_spot_checks(
        massive_bars=massive_bars,
        finnhub=finnhub,
        trade_date=trade_date,
    )

    source_plan: dict[str, int] = {}
    for bar in collected.values():
        source_plan[bar.source] = source_plan.get(bar.source, 0) + 1

    dry_run_payload = {
        "worker": MassiveDailyIngestionWorker.worker_name,
        "trade_date": trade_date.isoformat(),
        "active_universe": len(universe),
        "massive_batch_size": len(massive_bars),
        "planned_writes": len(collected),
        "planned_coverage": len(collected) / len(universe) if universe else 0.0,
        "primary_provider": "massive",
        "source_plan": source_plan,
        "fallback_symbols": [
            inst.symbol for inst, provider in provider_plan if provider != "massive"
        ],
        "missing_after_fallback": missing,
        "rejected_sample": rejected[:20],
        "finnhub_fallback_attempts": finnhub_attempts,
        "yfinance_fallback_attempts": yfinance_attempts,
        "fallback_budget_skipped": fallback_budget_exhausted,
        "spot_check_symbols": pick_spot_check_symbols(set(massive_bars)),
        "dry_run": True,
    }

    return {
        "bars_to_write": collected,
        "missing_symbols": missing,
        "spot_check_warnings": spot_warnings,
        "dry_run_payload": dry_run_payload,
    }


async def validate_with_db(
    conn: asyncpg.Connection,
    inst: UniverseInstrument,
    bar: DailyBar,
    prev_close: float | None,
) -> str | None:
    """Validate a bar using DB-backed corporate-action lookup."""
    corp = await has_corporate_action(conn, inst.instrument_id, bar.trade_date)
    reason = validate_bar(
        symbol=inst.symbol,
        open_=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        prev_close=prev_close,
        has_corporate_action=corp,
    )
    if reason:
        log.warning("bar_rejected", symbol=inst.symbol, reason=reason, source=bar.source)
    return reason


async def run_spot_checks(
    *,
    massive_bars: dict[str, DailyBar],
    finnhub: FinnhubClient,
    trade_date: date,
) -> list[str]:
    """Compare Massive vs Finnhub closes for liquid names; return WARN messages."""
    warnings: list[str] = []
    symbols = pick_spot_check_symbols(set(massive_bars))
    for symbol in symbols:
        massive_bar = massive_bars.get(symbol)
        if massive_bar is None:
            continue
        finn = await finnhub.daily_bar(symbol, trade_date)
        if finn is None or finn.close <= 0:
            continue
        divergence = abs(massive_bar.close / finn.close - 1.0)
        if divergence > 0.005:
            msg = (
                f"provider divergence: {symbol} massive={massive_bar.close:.4f} "
                f"finnhub={finn.close:.4f} ({divergence:.2%})"
            )
            warnings.append(msg)
            log.warning("spot_check_divergence", symbol=symbol, divergence=divergence)
    return warnings


async def upsert_price(conn: asyncpg.Connection, bar: DailyBar) -> None:
    """Upsert one canonical price row (worker owns canonical prices)."""
    row = bar_to_row(bar)
    await conn.execute(
        """
        INSERT INTO theeyebeta.prices_daily
            (instrument_id, ts, open, high, low, close, adj_close, volume, source, ingested_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
        ON CONFLICT (instrument_id, ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume,
            source = EXCLUDED.source,
            ingested_at = EXCLUDED.ingested_at
        """,
        *row,
    )


async def create_coverage_alert(
    conn: asyncpg.Connection,
    *,
    worker_name: str,
    run_id: int | None,
    trade_date: date,
    severity: str,
    missing_symbols: list[str],
    written: int,
    expected: int,
) -> None:
    """Insert audit_data_gaps + audit_alerts for sub-threshold coverage."""
    ratio = written / expected if expected else 0.0
    note = (
        f"MassiveDailyIngestionWorker coverage {ratio:.1%} "
        f"({written}/{expected}); missing={missing_symbols[:100]}"
    )
    day_start = datetime.combine(trade_date, time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    gap_id = await conn.fetchval(
        """
        INSERT INTO theeyebeta.audit_data_gaps
            (dataset_type, trade_date, expected_start, expected_end,
             expected_count, actual_count, gap_start, gap_end,
             severity, remediation_state, remediation_notes, metadata)
        VALUES (
            'prices_daily',
            $1::date,
            $2,
            $3,
            $4,
            $5,
            $2,
            $3,
            $6,
            'OPEN',
            $7,
            $8::jsonb
        )
        RETURNING gap_id
        """,
        trade_date,
        day_start,
        day_end,
        expected,
        written,
        severity,
        note,
        json.dumps({"missing_symbols": missing_symbols, "worker_name": worker_name}),
    )
    await conn.execute(
        """
        INSERT INTO theeyebeta.audit_alerts
            (alert_type, severity, trade_date, worker_name, gap_id, run_id,
             title, message, metadata)
        VALUES (
            'DATA_GAP',
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7,
            $8::jsonb
        )
        """,
        severity,
        trade_date,
        worker_name,
        gap_id,
        run_id,
        f"Canonical price coverage {severity}",
        note,
        json.dumps({"missing_symbols": missing_symbols}),
    )


async def create_provider_divergence_alert(
    conn: asyncpg.Connection,
    *,
    worker_name: str,
    run_id: int | None,
    trade_date: date,
    message: str,
) -> None:
    """Record a provider divergence WARN alert."""
    await conn.execute(
        """
        INSERT INTO theeyebeta.audit_alerts
            (alert_type, severity, trade_date, worker_name, run_id, title, message, metadata)
        VALUES (
            'PROVIDER_DIVERGENCE',
            'WARN',
            $1,
            $2,
            $3,
            'provider divergence',
            $4,
            $5::jsonb
        )
        """,
        trade_date,
        worker_name,
        run_id,
        message,
        json.dumps({"kind": "provider_divergence"}),
    )


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    worker = MassiveDailyIngestionWorker(target_symbol=getattr(args, "symbol", None))
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=None,
    )
    if not args.dry_run:
        print(
            json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MassiveDailyIngestionWorker")
    parser.add_argument("--date", help="Target calendar date YYYY-MM-DD; default today")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no DB writes")
    parser.add_argument(
        "--symbol",
        metavar="TICKER",
        default=None,
        help="Ingest only this ticker (case-insensitive); default: full universe",
    )
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
