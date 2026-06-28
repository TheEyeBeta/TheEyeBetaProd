#!/usr/bin/env python3
"""Multi-date price backfill with skip-if-present semantics and indicator recompute.

Writes theeyebeta.prices_daily first, then public.price_daily when needed.
Uses ON CONFLICT DO NOTHING — never overwrites existing provider bars.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = PROD_ROOT.parent / "TheEyeBetaLocal"

if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import (  # noqa: E402
    BaseWorker,
    WorkerResult,
    worker_database_url,
)

log = structlog.get_logger()

RECOMPUTE_DATES = [date(2026, 6, 8), date(2026, 6, 9)]
SKIP_COVERAGE_THRESHOLD = 0.95
WRITE_COVERAGE_THRESHOLD = 0.98
MAX_SINGLE_DAY_MOVE = 0.25
BACKFILL_SOURCE_TAG = "yfinance_backfill_prices"
MIRROR_SOURCE_TAG = "public_mirror_backfill"

SYNC_TABLES = (
    ("public.ind_technical_daily", "theeyebeta.ind_technical_daily"),
    ("public.ind_risk_daily", "theeyebeta.ind_risk_daily"),
    ("public.returns_snapshot_daily", "theeyebeta.returns_snapshot_daily"),
    ("public.ind_valuation_daily", "theeyebeta.ind_valuation_daily"),
)


@dataclass(slots=True)
class InstrumentRow:
    """Active instrument mapped to a public ticker."""

    instrument_id: int
    ticker_id: int
    symbol: str
    exchange_code: str


@dataclass(slots=True)
class SchemaDatePlan:
    """Per-(schema, date) backfill plan entry."""

    schema: str
    trade_date: date
    action: str
    current_count: int
    active_universe: int
    reason: str = ""


def _ensure_local_paths() -> None:
    paths = [
        LOCAL_ROOT / "packages" / "core" / "src",
        LOCAL_ROOT / "packages" / "data_access" / "src",
        LOCAL_ROOT / "packages" / "providers" / "src",
        LOCAL_ROOT / "services" / "etl" / "src",
        PROD_ROOT / "services" / "data_ingestion" / "src",
    ]
    for path in paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _make_ticker(symbol: str, exchange_code: str) -> str:
    from data_ingestion.adapters.yfinance import make_ticker

    return make_ticker(symbol, exchange_code)


def _parse_dates(raw: str | None) -> list[date] | None:
    if not raw:
        return None
    return [date.fromisoformat(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_schemas(raw: str) -> set[str]:
    if raw == "both":
        return {"theeyebeta", "public"}
    return {raw}


async def _load_universe(conn: asyncpg.Connection) -> list[InstrumentRow]:
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
        InstrumentRow(
            instrument_id=int(row["instrument_id"]),
            ticker_id=int(row["ticker_id"]),
            symbol=str(row["symbol"]),
            exchange_code=str(row["exchange_code"]),
        )
        for row in rows
    ]


async def _active_universe_count(conn: asyncpg.Connection) -> int:
    """Count active instruments that are mapped to public tickers (backfill universe)."""
    value = await conn.fetchval(
        """
        SELECT COUNT(*)
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
         WHERE i.active
        """,
    )
    return int(value or 0)


async def _schema_coverage(
    conn: asyncpg.Connection,
    schema: str,
    trade_date: date,
) -> int:
    if schema == "public":
        return int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                  FROM public.price_daily pd
                  JOIN theeyebeta.public_ticker_map m
                    ON m.public_ticker_id = pd.ticker_id
                 WHERE pd.date = $1
                """,
                trade_date,
            )
            or 0,
        )
    return int(
        await conn.fetchval(
            "SELECT COUNT(*) FROM theeyebeta.prices_daily WHERE ts::date = $1",
            trade_date,
        )
        or 0,
    )


async def _detect_missing_dates(
    conn: asyncpg.Connection,
    *,
    start: date,
    end: date,
) -> dict[str, list[date]]:
    active = await _active_universe_count(conn)
    threshold = int(active * SKIP_COVERAGE_THRESHOLD)
    trading_days = await conn.fetch(
        """
        SELECT calendar_date
          FROM public.trading_calendar
         WHERE is_trading_day
           AND calendar_date BETWEEN $1 AND $2
         ORDER BY calendar_date
        """,
        start,
        end,
    )
    missing: dict[str, list[date]] = {"public": [], "theeyebeta": []}
    for row in trading_days:
        trade_day: date = row["calendar_date"]
        for schema in ("public", "theeyebeta"):
            count = await _schema_coverage(conn, schema, trade_day)
            if count < threshold:
                missing[schema].append(trade_day)
    return missing


async def _assert_chunk_writable(conn: asyncpg.Connection, trade_date: date) -> None:
    ts = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
    row = await conn.fetchrow(
        """
        SELECT chunk_name, is_compressed
          FROM timescaledb_information.chunks
         WHERE hypertable_schema = 'theeyebeta'
           AND hypertable_name = 'prices_daily'
           AND range_start <= $1::timestamptz
           AND range_end > $1::timestamptz
         LIMIT 1
        """,
        ts,
    )
    if row is None:
        latest_end = await conn.fetchval(
            """
            SELECT MAX(range_end)
              FROM timescaledb_information.chunks
             WHERE hypertable_schema = 'theeyebeta'
               AND hypertable_name = 'prices_daily'
            """,
        )
        if latest_end is not None and ts >= latest_end:
            log.info("chunk_will_be_created", trade_date=trade_date.isoformat())
            return
        msg = f"No theeyebeta.prices_daily chunk found for {trade_date}"
        raise RuntimeError(msg)
    if bool(row["is_compressed"]):
        msg = (
            f"HARD STOP: {trade_date} falls in compressed chunk {row['chunk_name']}. "
            "Decompress manually before backfill."
        )
        raise RuntimeError(msg)


async def _prior_trading_day(conn: asyncpg.Connection, trade_date: date) -> date | None:
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM public.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )
    return value


async def _reference_closes(
    conn: asyncpg.Connection,
    ref_date: date,
    ticker_ids: list[int],
) -> dict[int, float]:
    rows = await conn.fetch(
        """
        SELECT ticker_id, close::float AS close
          FROM public.price_daily
         WHERE date = $1
           AND ticker_id = ANY($2::bigint[])
        """,
        ref_date,
        ticker_ids,
    )
    return {int(row["ticker_id"]): float(row["close"]) for row in rows}


async def _has_corporate_action(
    conn: asyncpg.Connection,
    ticker_id: int,
    trade_date: date,
) -> bool:
    value = await conn.fetchval(
        """
        SELECT 1
          FROM public.corporate_actions
         WHERE ticker_id = $1
           AND action_date BETWEEN ($2::date - 3) AND ($2::date + 3)
         LIMIT 1
        """,
        ticker_id,
        trade_date,
    )
    return value is not None


def _fetch_bar(inst: InstrumentRow, trade_date: date) -> dict[str, float | int] | None:
    from data_ingestion.adapters.yfinance import _fetch_sync

    ticker = _make_ticker(inst.symbol, inst.exchange_code)
    records = _fetch_sync(
        ticker,
        inst.instrument_id,
        inst.symbol,
        inst.exchange_code,
        trade_date,
    )
    if not records:
        return None
    record = records[0]
    return {
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "adj_close": record.adj_close or record.close,
        "volume": record.volume,
    }


def _validate_bar(
    bar: dict[str, float | int],
    *,
    ref_close: float | None,
    has_corp_action: bool,
    symbol: str,
) -> None:
    open_ = float(bar["open"])
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    if high < low:
        msg = f"{symbol}: high < low"
        raise ValueError(msg)
    for label, value in ("open", open_), ("high", high), ("low", low), ("close", close):
        if value <= 0:
            msg = f"{symbol}: non-positive {label}={value}"
            raise ValueError(msg)
    if ref_close and ref_close > 0 and not has_corp_action:
        move = abs(close / ref_close - 1.0)
        if move > MAX_SINGLE_DAY_MOVE:
            msg = f"{symbol}: |close/ref-1|={move:.1%} exceeds 25% without corporate action"
            raise ValueError(msg)


async def _copy_public_to_theeyebeta(conn: asyncpg.Connection, trade_date: date) -> int:
    ts = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
    result = await conn.execute(
        """
        INSERT INTO theeyebeta.prices_daily
            (instrument_id, ts, open, high, low, close, adj_close, volume, source)
        SELECT m.instrument_id,
               $2::timestamptz,
               pd.open,
               pd.high,
               pd.low,
               pd.close,
               pd.adj_close,
               pd.volume,
               $3
          FROM public.price_daily pd
          JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = pd.ticker_id
         WHERE pd.date = $1
        ON CONFLICT (instrument_id, ts) DO NOTHING
        """,
        trade_date,
        ts,
        MIRROR_SOURCE_TAG,
    )
    return int(result.split()[-1]) if result else 0


async def _write_theeyebeta_yfinance(
    conn: asyncpg.Connection,
    trade_date: date,
    bars: list[tuple[InstrumentRow, dict[str, float | int]]],
) -> int:
    ts = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
    written = 0
    for inst, bar in bars:
        result = await conn.execute(
            """
            INSERT INTO theeyebeta.prices_daily
                (instrument_id, ts, open, high, low, close, adj_close, volume, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (instrument_id, ts) DO NOTHING
            """,
            inst.instrument_id,
            ts,
            Decimal(str(bar["open"])),
            Decimal(str(bar["high"])),
            Decimal(str(bar["low"])),
            Decimal(str(bar["close"])),
            Decimal(str(bar["adj_close"])),
            int(bar["volume"]),
            BACKFILL_SOURCE_TAG,
        )
        if result and result.endswith("1"):
            written += 1
    return written


async def _write_public_yfinance(
    conn: asyncpg.Connection,
    trade_date: date,
    bars: list[tuple[InstrumentRow, dict[str, float | int]]],
) -> int:
    written = 0
    for inst, bar in bars:
        result = await conn.execute(
            """
            INSERT INTO public.price_daily
                (ticker_id, date, open, high, low, close, adj_close, volume, data_source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (ticker_id, date) DO NOTHING
            """,
            inst.ticker_id,
            trade_date,
            Decimal(str(bar["open"])),
            Decimal(str(bar["high"])),
            Decimal(str(bar["low"])),
            Decimal(str(bar["close"])),
            Decimal(str(bar["adj_close"])),
            int(bar["volume"]),
            BACKFILL_SOURCE_TAG,
        )
        if result and result.endswith("1"):
            written += 1
    return written


async def _missing_instruments(
    conn: asyncpg.Connection,
    universe: list[InstrumentRow],
    trade_date: date,
) -> list[InstrumentRow]:
    """Return active-universe instruments without a theeyebeta bar on trade_date."""
    rows = await conn.fetch(
        """
        SELECT m.instrument_id
          FROM theeyebeta.public_ticker_map m
          JOIN theeyebeta.instruments i ON i.id = m.instrument_id AND i.active
         WHERE NOT EXISTS (
               SELECT 1
                 FROM theeyebeta.prices_daily pd
                WHERE pd.instrument_id = m.instrument_id
                  AND pd.ts::date = $1
           )
        """,
        trade_date,
    )
    missing_ids = {int(row["instrument_id"]) for row in rows}
    return [inst for inst in universe if inst.instrument_id in missing_ids]


async def _supplement_theeyebeta_gaps(
    conn: asyncpg.Connection,
    universe: list[InstrumentRow],
    trade_date: date,
) -> int:
    """Fill mirror gaps with yfinance for instruments still missing after public copy."""
    missing = await _missing_instruments(conn, universe, trade_date)
    if not missing:
        return 0
    bars, _rejected = await _collect_yfinance_bars(conn, missing, trade_date)
    return await _write_theeyebeta_yfinance(conn, trade_date, bars)


async def _collect_yfinance_bars(
    conn: asyncpg.Connection,
    universe: list[InstrumentRow],
    trade_date: date,
) -> tuple[list[tuple[InstrumentRow, dict[str, float | int]]], list[str]]:
    ref_date = await _prior_trading_day(conn, trade_date)
    refs: dict[int, float] = {}
    if ref_date is not None:
        refs = await _reference_closes(conn, ref_date, [inst.ticker_id for inst in universe])

    valid_bars: list[tuple[InstrumentRow, dict[str, float | int]]] = []
    rejected: list[str] = []
    for inst in universe:
        try:
            bar = await asyncio.to_thread(_fetch_bar, inst, trade_date)
            if bar is None:
                rejected.append(inst.symbol)
                continue
            corp = await _has_corporate_action(conn, inst.ticker_id, trade_date)
            _validate_bar(
                bar,
                ref_close=refs.get(inst.ticker_id),
                has_corp_action=corp,
                symbol=inst.symbol,
            )
            valid_bars.append((inst, bar))
        except Exception as exc:
            log.warning(
                "bar_rejected",
                symbol=inst.symbol,
                trade_date=trade_date.isoformat(),
                error=str(exc),
            )
            rejected.append(inst.symbol)
    return valid_bars, rejected


async def _assert_post_write_coverage(
    conn: asyncpg.Connection,
    schema: str,
    trade_date: date,
    *,
    active: int,
    rejected: list[str] | None = None,
) -> int:
    count = await _schema_coverage(conn, schema, trade_date)
    coverage = count / active if active else 0.0
    if coverage < WRITE_COVERAGE_THRESHOLD:
        missing = rejected or []
        msg = (
            f"FAILED {schema} {trade_date}: coverage {coverage:.1%} "
            f"below {WRITE_COVERAGE_THRESHOLD:.0%}; missing sample={missing[:30]}"
        )
        raise RuntimeError(msg)
    return count


def _build_work_items(
    schemas: set[str],
    missing: dict[str, list[date]],
    explicit_dates: list[date] | None,
) -> list[tuple[str, date]]:
    items: list[tuple[str, date]] = []
    if explicit_dates is not None:
        for trade_day in explicit_dates:
            for schema in sorted(schemas):
                items.append((schema, trade_day))
        return items

    for schema in sorted(schemas):
        for trade_day in missing.get(schema, []):
            items.append((schema, trade_day))
    return items


async def _build_plan(
    conn: asyncpg.Connection,
    work_items: list[tuple[str, date]],
) -> list[SchemaDatePlan]:
    active = await _active_universe_count(conn)
    threshold = int(active * SKIP_COVERAGE_THRESHOLD)
    plan: list[SchemaDatePlan] = []
    for schema, trade_day in work_items:
        count = await _schema_coverage(conn, schema, trade_day)
        if count >= threshold:
            plan.append(
                SchemaDatePlan(
                    schema=schema,
                    trade_date=trade_day,
                    action="skip",
                    current_count=count,
                    active_universe=active,
                    reason="coverage already >=95%",
                ),
            )
            continue

        if schema == "theeyebeta":
            public_count = await _schema_coverage(conn, "public", trade_day)
            action = "mirror_public" if public_count >= threshold else "yfinance"
        else:
            action = "yfinance"

        plan.append(
            SchemaDatePlan(
                schema=schema,
                trade_date=trade_day,
                action=action,
                current_count=count,
                active_universe=active,
            ),
        )
    return plan


def _recompute_public_for_date(trade_date: date) -> dict[str, object]:
    _ensure_local_paths()
    from core.pipeline.daily_pipeline import run_daily_pipeline

    summary = run_daily_pipeline(
        mode="compute_only",
        target_date=trade_date,
        force_update=True,
        skip_if_not_trading_day=False,
        post_close_delay_hours=0.0,
    )
    return json.loads(summary.to_json())


async def _table_columns(conn: asyncpg.Connection, table_name: str) -> list[str]:
    schema, table = table_name.split(".", 1)
    rows = await conn.fetch(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = $1
           AND table_name = $2
         ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    return [str(row["column_name"]) for row in rows]


async def _sync_table_for_dates(
    conn: asyncpg.Connection,
    source: str,
    target: str,
    dates: list[date],
) -> int:
    source_cols = await _table_columns(conn, source)
    target_cols = await _table_columns(conn, target)
    common = [col for col in source_cols if col in target_cols and col not in {"instrument_id"}]
    if "ticker_id" not in common or "date" not in common:
        msg = f"Cannot sync {source} -> {target}: missing ticker_id/date"
        raise RuntimeError(msg)

    insert_cols = [*common, "instrument_id"]
    select_exprs = [f"s.{col}" for col in common] + ["m.instrument_id"]
    update_cols = [col for col in insert_cols if col not in {"instrument_id", "date"}]
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
    order_terms = ["m.instrument_id", "s.date"]
    if "computed_at" in common:
        order_terms.append("s.computed_at DESC NULLS LAST")

    sql = f"""
        INSERT INTO {target} ({", ".join(insert_cols)})
        SELECT DISTINCT ON (m.instrument_id, s.date)
            {", ".join(select_exprs)}
          FROM {source} s
          JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = s.ticker_id
         WHERE s.date = ANY($1::date[])
         ORDER BY {", ".join(order_terms)}
        ON CONFLICT (instrument_id, date) DO UPDATE SET
            {updates}
    """  # noqa: S608
    result = await conn.execute(sql, dates)
    return int(result.split()[-1]) if result else 0


async def _analyze_partitions(conn: asyncpg.Connection, dates: list[date]) -> None:
    if any(d.year == 2026 for d in dates):
        await conn.execute("ANALYZE public.price_daily_y2026")

    min_date = min(dates)
    max_date = max(dates)
    chunks = await conn.fetch(
        """
        SELECT chunk_schema || '.' || chunk_name AS chunk
          FROM timescaledb_information.chunks
         WHERE hypertable_schema = 'theeyebeta'
           AND hypertable_name = 'prices_daily'
           AND range_start <= $2::timestamptz
           AND range_end > $1::timestamptz
        """,
        datetime(min_date.year, min_date.month, min_date.day, tzinfo=UTC),
        datetime(max_date.year, max_date.month, max_date.day, tzinfo=UTC) + timedelta(days=1),
    )
    for row in chunks:
        await conn.execute(f"ANALYZE {row['chunk']}")


async def _remediate_backfill_gaps(conn: asyncpg.Connection, dates: list[date]) -> None:
    for trade_day in dates:
        await conn.execute(
            """
            UPDATE public.audit_data_gaps
               SET remediation_state = 'RESOLVED',
                   remediation_notes = COALESCE(remediation_notes, '')
                       || ' | Backfilled via scripts/backfill_prices.py',
                   updated_at = now()
             WHERE trade_date = $1
               AND remediation_state = 'OPEN'
               AND remediation_notes ILIKE '%pipeline completion%'
            """,
            trade_day,
        )
        await conn.execute(
            """
            UPDATE public.audit_alerts
               SET resolved_at = now(),
                   resolution_notes = 'Resolved by scripts/backfill_prices.py',
                   updated_at = now()
             WHERE trade_date = $1
               AND gap_id IS NOT NULL
               AND resolved_at IS NULL
            """,
            trade_day,
        )


async def run_backfill(
    *,
    dry_run: bool,
    schemas: set[str],
    explicit_dates: list[date] | None,
) -> dict[str, object]:
    """Execute multi-date price backfill and indicator recompute."""
    conn = await asyncpg.connect(worker_database_url())
    try:
        universe = await _load_universe(conn)
        active = await _active_universe_count(conn)
        missing = await _detect_missing_dates(
            conn,
            start=date(2026, 6, 2),
            end=date(2026, 6, 9),
        )
        work_items = _build_work_items(schemas, missing, explicit_dates)
        plan = await _build_plan(conn, work_items)

        plan_payload = [
            {
                "schema": item.schema,
                "trade_date": item.trade_date.isoformat(),
                "action": item.action,
                "current_count": item.current_count,
                "active_universe": item.active_universe,
                "reason": item.reason,
            }
            for item in plan
        ]

        if dry_run:
            return {
                "dry_run": True,
                "active_universe": active,
                "detected_missing": {k: [d.isoformat() for d in v] for k, v in missing.items()},
                "plan": plan_payload,
                "recompute_dates": [d.isoformat() for d in RECOMPUTE_DATES],
            }

        write_results: list[dict[str, object]] = []
        yfinance_cache: dict[date, list[tuple[InstrumentRow, dict[str, float | int]]]] = {}

        theeyebeta_items = [
            item for item in plan if item.schema == "theeyebeta" and item.action != "skip"
        ]
        public_items = [item for item in plan if item.schema == "public" and item.action != "skip"]

        for item in theeyebeta_items:
            await _assert_chunk_writable(conn, item.trade_date)
            if item.action == "mirror_public":
                written = await _copy_public_to_theeyebeta(conn, item.trade_date)
                written += await _supplement_theeyebeta_gaps(conn, universe, item.trade_date)
                action = "mirror_public"
            else:
                if item.trade_date not in yfinance_cache:
                    bars, rejected = await _collect_yfinance_bars(conn, universe, item.trade_date)
                    coverage = len(bars) / active if active else 0.0
                    if coverage < WRITE_COVERAGE_THRESHOLD:
                        msg = (
                            f"yfinance prefetch {item.trade_date}: {coverage:.1%} "
                            f"below {WRITE_COVERAGE_THRESHOLD:.0%}: {rejected[:30]}"
                        )
                        raise RuntimeError(msg)
                    yfinance_cache[item.trade_date] = bars
                written = await _write_theeyebeta_yfinance(
                    conn,
                    item.trade_date,
                    yfinance_cache[item.trade_date],
                )
                action = "yfinance"
            final_count = await _assert_post_write_coverage(
                conn,
                "theeyebeta",
                item.trade_date,
                active=active,
            )
            write_results.append(
                {
                    "schema": "theeyebeta",
                    "trade_date": item.trade_date.isoformat(),
                    "action": action,
                    "rows_written": written,
                    "final_count": final_count,
                },
            )

        for item in public_items:
            if item.trade_date not in yfinance_cache:
                bars, rejected = await _collect_yfinance_bars(conn, universe, item.trade_date)
                coverage = len(bars) / active if active else 0.0
                if coverage < WRITE_COVERAGE_THRESHOLD:
                    msg = (
                        f"yfinance prefetch {item.trade_date}: {coverage:.1%} "
                        f"below {WRITE_COVERAGE_THRESHOLD:.0%}: {rejected[:30]}"
                    )
                    raise RuntimeError(msg)
                yfinance_cache[item.trade_date] = bars
            written = await _write_public_yfinance(
                conn,
                item.trade_date,
                yfinance_cache[item.trade_date],
            )
            final_count = await _assert_post_write_coverage(
                conn,
                "public",
                item.trade_date,
                active=active,
            )
            write_results.append(
                {
                    "schema": "public",
                    "trade_date": item.trade_date.isoformat(),
                    "action": "yfinance",
                    "rows_written": written,
                    "final_count": final_count,
                },
            )

        recompute_meta: list[dict[str, object]] = []
        for trade_day in RECOMPUTE_DATES:
            log.info("recompute_start", trade_date=trade_day.isoformat())
            summary = await asyncio.to_thread(_recompute_public_for_date, trade_day)
            recompute_meta.append(summary)

        sync_counts: dict[str, int] = {}
        for source, target in SYNC_TABLES:
            sync_counts[target] = await _sync_table_for_dates(conn, source, target, RECOMPUTE_DATES)

        touched_dates = sorted({item.trade_date for item in plan if item.action != "skip"})
        if touched_dates:
            await _analyze_partitions(conn, touched_dates)
        backfilled_dates = sorted(
            {
                item.trade_date
                for item in plan
                if item.action != "skip" and item.trade_date in RECOMPUTE_DATES
            },
        )
        if backfilled_dates:
            await _remediate_backfill_gaps(conn, backfilled_dates)

        return {
            "dry_run": False,
            "active_universe": active,
            "plan": plan_payload,
            "write_results": write_results,
            "recompute_dates": [d.isoformat() for d in RECOMPUTE_DATES],
            "sync_counts": sync_counts,
            "recompute": recompute_meta,
        }
    finally:
        await conn.close()


class BackfillPricesWorker(BaseWorker):
    """Audit-wrapped runner for multi-date price backfill."""

    worker_name = "BackfillPrices"
    worker_type = "recovery"
    display_name = "Price Backfill"

    def __init__(
        self,
        *,
        schemas: set[str] | None = None,
        explicit_dates: list[date] | None = None,
        database_url: str | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
        self.schemas = schemas or {"theeyebeta", "public"}
        self.explicit_dates = explicit_dates

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        del conn
        metadata = await run_backfill(
            dry_run=dry_run,
            schemas=self.schemas,
            explicit_dates=self.explicit_dates,
        )
        records = sum(
            int(row.get("rows_written", 0) or 0) for row in metadata.get("write_results", [])
        )
        return WorkerResult(
            records_written=records,
            records_expected=int(metadata.get("active_universe", 0) or 0),
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    schemas = _parse_schemas(args.schemas)
    explicit_dates = _parse_dates(args.dates)
    anchor = explicit_dates[0] if explicit_dates else date(2026, 6, 8)
    worker = BackfillPricesWorker(schemas=schemas, explicit_dates=explicit_dates)
    result = await worker.run(
        anchor,
        run_type="recovery",
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing daily prices and recompute indicators",
    )
    parser.add_argument(
        "--dates",
        help="Comma-separated trade dates (default: auto-detect MISSING from 2026-06-02..06-10)",
    )
    parser.add_argument(
        "--schemas",
        default="both",
        choices=["both", "theeyebeta", "public"],
        help="Target schema(s) for price backfill",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview per-(schema,date) plan")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
