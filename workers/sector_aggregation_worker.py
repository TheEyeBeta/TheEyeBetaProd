"""Per-sector daily aggregates from canonical theeyebeta prices and indicators.

Methodology (documented choices):
    - Equal-weight: every per-sector average is a simple mean across member
      instruments. Cap-weighting is deferred until market-cap data is native
      to theeyebeta.
    - Return windows use trading-row offsets (ROW_NUMBER over ordered ts),
      never calendar arithmetic.
    - volume_ratio_20d per instrument = volume_D / mean(volume of the prior
      20 trading rows, excluding D); the sector value is the mean of member
      ratios.
    - NULL policy: an instrument missing an input is excluded from that
      metric's aggregate; if more than ``NULL_POLICY_MAX_MISSING`` of a
      sector's members lack the input, the sector metric is NULL.
    - S&P 500 return source: yfinance ^GSPC closes (tier 1), SPY closes from
      theeyebeta.prices_daily as a proxy (tier 2, tagged), else NULL + WARN.

CLI examples:
    python -m workers.sector_aggregation_worker --dry-run
    python -m workers.sector_aggregation_worker --date 2026-06-10 --run-type manual
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date
from statistics import fmean, median
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult

log = structlog.get_logger()

NULL_POLICY_MAX_MISSING = 0.30
RETURN_WINDOWS = (1, 5, 30)
VOLUME_WINDOW = 20
SPX_WINDOW = 30
TOP_CONTRIBUTORS = 3

# Per-instrument inputs for trade date D: trading-row offset closes for the
# return windows, prior-20-row average volume, and date-D technical levels.
INSTRUMENT_ROWS_SQL = """
WITH universe AS (
    SELECT i.id AS instrument_id, i.symbol, i.sector
      FROM theeyebeta.instruments i
      JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
     WHERE i.active
       AND i.asset_class IN ('equity', 'adr')
),
ranked AS (
    SELECT p.instrument_id,
           p.ts::date AS d,
           p.close,
           p.volume,
           ROW_NUMBER() OVER (
               PARTITION BY p.instrument_id ORDER BY p.ts DESC
           ) AS rn
      FROM theeyebeta.prices_daily p
      JOIN universe u ON u.instrument_id = p.instrument_id
     WHERE p.ts::date <= $1
       AND p.ts::date > $1 - INTERVAL '400 days'
       AND p.close IS NOT NULL
       AND p.close > 0
),
vol20 AS (
    SELECT instrument_id, AVG(volume) AS avg_volume_20d
      FROM ranked
     WHERE rn BETWEEN 2 AND 21
       AND volume IS NOT NULL
     GROUP BY instrument_id
    HAVING COUNT(*) = 20
)
SELECT u.instrument_id,
       u.symbol,
       COALESCE(NULLIF(u.sector, ''), 'UNKNOWN') AS sector,
       cur.close   AS close_d,
       cur.volume  AS volume_d,
       r1.close    AS close_1,
       r5.close    AS close_5,
       r30.close   AS close_30,
       v.avg_volume_20d,
       ind.rsi_14,
       ind.sma_50,
       ind.sma_200
  FROM universe u
  JOIN ranked cur
    ON cur.instrument_id = u.instrument_id AND cur.rn = 1 AND cur.d = $1
  LEFT JOIN ranked r1
    ON r1.instrument_id = u.instrument_id AND r1.rn = 2
  LEFT JOIN ranked r5
    ON r5.instrument_id = u.instrument_id AND r5.rn = 6
  LEFT JOIN ranked r30
    ON r30.instrument_id = u.instrument_id AND r30.rn = 31
  LEFT JOIN vol20 v ON v.instrument_id = u.instrument_id
  LEFT JOIN theeyebeta.ind_technical_daily ind
    ON ind.instrument_id = u.instrument_id AND ind.date = $1
 ORDER BY u.symbol
"""

SPY_CLOSES_SQL = """
SELECT p.close
  FROM theeyebeta.prices_daily p
  JOIN theeyebeta.instruments i ON i.id = p.instrument_id
 WHERE i.symbol = 'SPY'
   AND p.ts::date <= $1
   AND p.close IS NOT NULL
 ORDER BY p.ts DESC
 LIMIT $2
"""

UPSERT_SQL = """
INSERT INTO theeyebeta.sector_daily (
    sector, as_of_date, n_instruments,
    avg_return_1d, avg_return_5d, avg_return_30d,
    median_rsi_14, pct_above_sma_50, pct_above_sma_200,
    rel_strength_spx_30d, rotation_rank, volume_ratio_20d,
    top_contributors
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
ON CONFLICT (sector, as_of_date) DO UPDATE SET
    n_instruments        = EXCLUDED.n_instruments,
    avg_return_1d        = EXCLUDED.avg_return_1d,
    avg_return_5d        = EXCLUDED.avg_return_5d,
    avg_return_30d       = EXCLUDED.avg_return_30d,
    median_rsi_14        = EXCLUDED.median_rsi_14,
    pct_above_sma_50     = EXCLUDED.pct_above_sma_50,
    pct_above_sma_200    = EXCLUDED.pct_above_sma_200,
    rel_strength_spx_30d = EXCLUDED.rel_strength_spx_30d,
    rotation_rank        = EXCLUDED.rotation_rank,
    volume_ratio_20d     = EXCLUDED.volume_ratio_20d,
    top_contributors     = EXCLUDED.top_contributors,
    created_at           = now()
"""


@dataclass(slots=True)
class InstrumentInputs:
    """Per-instrument raw inputs for one trade date."""

    symbol: str
    sector: str
    return_1d: float | None
    return_5d: float | None
    return_30d: float | None
    rsi_14: float | None
    above_sma_50: bool | None
    above_sma_200: bool | None
    volume_ratio_20d: float | None


@dataclass(slots=True)
class SectorAggregate:
    """One theeyebeta.sector_daily row before rank assignment."""

    sector: str
    n_instruments: int
    avg_return_1d: float | None
    avg_return_5d: float | None
    avg_return_30d: float | None
    median_rsi_14: float | None
    pct_above_sma_50: float | None
    pct_above_sma_200: float | None
    rel_strength_spx_30d: float | None
    rotation_rank: int | None
    volume_ratio_20d: float | None
    top_contributors: list[dict[str, Any]]


def _ret(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1.0


def instrument_inputs_from_row(row: dict[str, Any]) -> InstrumentInputs:
    """Convert one SQL row into typed per-instrument inputs."""
    close_d = float(row["close_d"]) if row["close_d"] is not None else None
    sma_50 = float(row["sma_50"]) if row["sma_50"] is not None else None
    sma_200 = float(row["sma_200"]) if row["sma_200"] is not None else None
    avg_vol = float(row["avg_volume_20d"]) if row["avg_volume_20d"] is not None else None
    volume_d = float(row["volume_d"]) if row["volume_d"] is not None else None

    volume_ratio = None
    if volume_d is not None and avg_vol is not None and avg_vol > 0:
        volume_ratio = volume_d / avg_vol

    return InstrumentInputs(
        symbol=row["symbol"],
        sector=row["sector"],
        return_1d=_ret(close_d, float(row["close_1"]) if row["close_1"] is not None else None),
        return_5d=_ret(close_d, float(row["close_5"]) if row["close_5"] is not None else None),
        return_30d=_ret(close_d, float(row["close_30"]) if row["close_30"] is not None else None),
        rsi_14=float(row["rsi_14"]) if row["rsi_14"] is not None else None,
        above_sma_50=(close_d > sma_50) if close_d is not None and sma_50 is not None else None,
        above_sma_200=(close_d > sma_200) if close_d is not None and sma_200 is not None else None,
        volume_ratio_20d=volume_ratio,
    )


def _policy_mean(values: list[float | None], n_members: int) -> float | None:
    """Mean with the NULL policy: NULL when too many members lack the input."""
    present = [v for v in values if v is not None]
    if not present or n_members == 0:
        return None
    if (n_members - len(present)) / n_members > NULL_POLICY_MAX_MISSING:
        return None
    return fmean(present)


def _policy_median(values: list[float | None], n_members: int) -> float | None:
    present = [v for v in values if v is not None]
    if not present or n_members == 0:
        return None
    if (n_members - len(present)) / n_members > NULL_POLICY_MAX_MISSING:
        return None
    return float(median(present))


def _policy_pct_true(values: list[bool | None], n_members: int) -> float | None:
    present = [v for v in values if v is not None]
    if not present or n_members == 0:
        return None
    if (n_members - len(present)) / n_members > NULL_POLICY_MAX_MISSING:
        return None
    return 100.0 * sum(1 for v in present if v) / len(present)


def aggregate_sectors(
    instruments: list[InstrumentInputs],
    spx_return_30d: float | None,
) -> list[SectorAggregate]:
    """Aggregate per-instrument inputs into per-sector rows with rotation ranks."""
    by_sector: dict[str, list[InstrumentInputs]] = {}
    for inst in instruments:
        by_sector.setdefault(inst.sector, []).append(inst)

    aggregates: list[SectorAggregate] = []
    for sector in sorted(by_sector):
        members = by_sector[sector]
        n = len(members)
        avg_r30 = _policy_mean([m.return_30d for m in members], n)
        rel_strength = (
            avg_r30 - spx_return_30d if avg_r30 is not None and spx_return_30d is not None else None
        )
        contributors = sorted(
            (m for m in members if m.return_1d is not None),
            key=lambda m: (-m.return_1d, m.symbol),
        )[:TOP_CONTRIBUTORS]
        aggregates.append(
            SectorAggregate(
                sector=sector,
                n_instruments=n,
                avg_return_1d=_policy_mean([m.return_1d for m in members], n),
                avg_return_5d=_policy_mean([m.return_5d for m in members], n),
                avg_return_30d=avg_r30,
                median_rsi_14=_policy_median([m.rsi_14 for m in members], n),
                pct_above_sma_50=_policy_pct_true([m.above_sma_50 for m in members], n),
                pct_above_sma_200=_policy_pct_true([m.above_sma_200 for m in members], n),
                rel_strength_spx_30d=rel_strength,
                rotation_rank=None,
                volume_ratio_20d=_policy_mean([m.volume_ratio_20d for m in members], n),
                top_contributors=[
                    {"symbol": m.symbol, "return_1d": round(m.return_1d, 6)}
                    for m in contributors
                    if m.return_1d is not None
                ],
            ),
        )

    # DENSE_RANK over rel_strength descending; deterministic for ties (equal
    # values share a rank); NULL rel_strength keeps a NULL rank.
    ranked_values = sorted(
        {a.rel_strength_spx_30d for a in aggregates if a.rel_strength_spx_30d is not None},
        reverse=True,
    )
    rank_of = {value: idx + 1 for idx, value in enumerate(ranked_values)}
    for agg in aggregates:
        if agg.rel_strength_spx_30d is not None:
            agg.rotation_rank = rank_of[agg.rel_strength_spx_30d]
    return aggregates


def compute_window_return(closes_desc: list[float], window: int) -> float | None:
    """Return close_0/close_window - 1 from a newest-first close series."""
    if len(closes_desc) <= window:
        return None
    now = closes_desc[0]
    then = closes_desc[window]
    if then <= 0:
        return None
    return now / then - 1.0


def fetch_gspc_return_30d(trade_date: date) -> float | None:
    """Fetch ^GSPC closes via yfinance and compute the 30-trading-day return.

    Returns None when yfinance is unavailable, the series does not include
    ``trade_date``, or history is too short.
    """
    try:
        import yfinance as yf

        history = yf.Ticker("^GSPC").history(period="4mo", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001 - provider failure is non-fatal
        log.warning("gspc_fetch_failed", error=str(exc))
        return None
    if history is None or history.empty:
        return None
    closes = history["Close"].dropna()
    dates = [d.date() for d in closes.index]
    if not dates or dates[-1] != trade_date:
        log.warning(
            "gspc_series_misses_target",
            latest=str(dates[-1]) if dates else None,
            target=trade_date.isoformat(),
        )
        return None
    closes_desc = [float(v) for v in reversed(closes.tolist())]
    return compute_window_return(closes_desc, SPX_WINDOW)


async def fetch_spy_proxy_return_30d(
    conn: asyncpg.Connection,
    trade_date: date,
) -> float | None:
    """SPY-close proxy for the S&P 500 30-trading-day return (tier 2)."""
    rows = await conn.fetch(SPY_CLOSES_SQL, trade_date, SPX_WINDOW + 1)
    closes_desc = [float(r["close"]) for r in rows]
    return compute_window_return(closes_desc, SPX_WINDOW)


class SectorAggregationWorker(BaseWorker):
    """Compute and upsert theeyebeta.sector_daily for a trade date."""

    worker_name = "SectorAggregationWorker"
    worker_type = "sector_aggregation"
    display_name = "Sector Aggregation"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)

        # Precondition: indicators for the chain (massive ingest -> indicators
        # -> sector) must exist. Fail loudly so the harness surfaces it.
        ind_rows = await conn.fetchval(
            "SELECT COUNT(*) FROM theeyebeta.ind_technical_daily WHERE date = $1",
            target,
        )
        if not ind_rows:
            msg = (
                f"Precondition failed: theeyebeta.ind_technical_daily has no rows "
                f"for {target.isoformat()}; sector aggregation requires the "
                f"indicator step to have completed first."
            )
            raise RuntimeError(msg)

        rows = await conn.fetch(INSTRUMENT_ROWS_SQL, target)
        instruments = [instrument_inputs_from_row(dict(row)) for row in rows]
        if not instruments:
            msg = f"No instrument price rows for {target.isoformat()}; nothing to aggregate."
            raise RuntimeError(msg)

        spx_return = await asyncio.to_thread(fetch_gspc_return_30d, target)
        spx_source = "yfinance_^GSPC"
        if spx_return is None:
            spx_return = await fetch_spy_proxy_return_30d(conn, target)
            spx_source = "SPY_proxy" if spx_return is not None else "unavailable"
        if spx_return is None and not dry_run:
            await conn.execute(
                """
                INSERT INTO theeyebeta.audit_alerts
                    (alert_type, severity, trade_date, worker_name, title, message, metadata)
                VALUES ('DATA_GAP', 'WARN', $1, $2, $3, $4, $5::jsonb)
                """,
                target,
                self.worker_name,
                "SPX return unavailable",
                "Neither ^GSPC (yfinance) nor SPY proxy could provide a "
                "30-trading-day S&P 500 return; rel_strength/rotation_rank are NULL.",
                json.dumps({"spx_source": spx_source}),
            )

        aggregates = aggregate_sectors(instruments, spx_return)

        metadata: dict[str, Any] = {
            "as_of_date": target.isoformat(),
            "instruments": len(instruments),
            "sectors": len(aggregates),
            "spx_source": spx_source,
            "spx_return_30d": spx_return,
        }
        if dry_run:
            payload = {
                "worker": self.worker_name,
                "dry_run": True,
                **metadata,
                "rows": [
                    {
                        "sector": a.sector,
                        "n_instruments": a.n_instruments,
                        "avg_return_1d": a.avg_return_1d,
                        "rel_strength_spx_30d": a.rel_strength_spx_30d,
                        "rotation_rank": a.rotation_rank,
                    }
                    for a in aggregates
                ],
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return WorkerResult(records_written=0, records_expected=len(aggregates))

        written = 0
        for a in aggregates:
            await conn.execute(
                UPSERT_SQL,
                a.sector,
                target,
                a.n_instruments,
                _round(a.avg_return_1d, 6),
                _round(a.avg_return_5d, 6),
                _round(a.avg_return_30d, 6),
                _round(a.median_rsi_14, 4),
                _round(a.pct_above_sma_50, 3),
                _round(a.pct_above_sma_200, 3),
                _round(a.rel_strength_spx_30d, 6),
                a.rotation_rank,
                _round(a.volume_ratio_20d, 4),
                json.dumps(a.top_contributors),
            )
            written += 1

        log.info("sector_daily_written", **metadata, rows=written)
        return WorkerResult(
            records_written=written,
            records_expected=len(aggregates),
            metadata=metadata,
        )


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


async def resolve_target_trade_date(conn: asyncpg.Connection, trade_date: date) -> date:
    """Return the latest trading day on or before trade_date."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date <= $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )
    if value is not None:
        return value
    has_data = await conn.fetchval(
        """
        SELECT 1
          FROM theeyebeta.ind_technical_daily
         WHERE date = $1
         LIMIT 1
        """,
        trade_date,
    )
    if has_data:
        return trade_date
    msg = f"No trading day found on or before {trade_date.isoformat()}"
    raise RuntimeError(msg)


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    worker = SectorAggregationWorker()
    result = await worker.run(
        _parse_date(args.date),
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "worker": worker.worker_name,
                "records_written": result.records_written,
                **result.metadata,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run the sector aggregation worker")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; defaults to latest trading day")
    parser.add_argument(
        "--run-type",
        default="scheduled",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
