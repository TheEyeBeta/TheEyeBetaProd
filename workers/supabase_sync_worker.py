"""Supabase sync — publish theeyebeta.latest_snapshots to advisor stock_snapshots."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import structlog

from workers.base_worker import BaseWorker, WorkerResult

log = structlog.get_logger()

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
BATCH_SIZE = 500

FETCH_SNAPSHOTS_SQL = """
SELECT
    ls.ticker_id,
    i.symbol AS ticker,
    COALESCE(i.metadata->>'company_name', i.metadata->>'name', i.symbol) AS company_name,
    ls.last_price,
    ls.last_price_ts,
    ls.price_change_pct,
    ls.price_change_abs,
    ls.high_52w,
    ls.low_52w,
    ls.updated_at,
    ls.volume,
    ls.avg_volume_10d,
    ls.avg_volume_30d,
    ls.volume_ratio,
    ls.sma_10,
    ls.sma_20,
    ls.sma_50,
    ls.sma_100,
    ls.sma_200,
    ls.ema_10,
    ls.ema_20,
    ls.ema_50,
    ls.ema_200,
    ls.rsi_14,
    ls.rsi_9,
    ls.macd,
    ls.macd_signal,
    ls.macd_hist,
    ls.stochastic_k,
    ls.stochastic_d,
    ls.williams_r,
    ls.cci,
    ls.adx,
    ls.bollinger_upper,
    ls.bollinger_middle,
    ls.bollinger_lower,
    ls.pe_ratio,
    ls.forward_pe,
    ls.peg_ratio,
    ls.price_to_book,
    ls.price_to_sales,
    ls.dividend_yield,
    ls.market_cap,
    ls.eps,
    ls.eps_growth,
    ls.revenue_growth,
    ls.price_vs_sma_50,
    ls.price_vs_sma_200,
    ls.price_vs_ema_50,
    ls.price_vs_ema_200,
    ls.price_vs_bollinger_middle,
    ls.is_bullish,
    ls.is_oversold,
    ls.is_overbought,
    ls.latest_signal,
    ls.signal_strategy,
    ls.signal_confidence,
    ls.signal_ts,
    ls.last_news_ts,
    ls.news_count_24h
FROM theeyebeta.latest_snapshots ls
JOIN theeyebeta.instruments i ON i.id = ls.instrument_id
JOIN theeyebeta.public_ticker_map m ON m.instrument_id = ls.instrument_id
WHERE ls.ticker_id IS NOT NULL
ORDER BY ls.updated_at DESC NULLS LAST
"""


def safe_float(value: object) -> float | None:
    """Convert a value to float, rejecting NaN and infinity."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def to_iso(value: object) -> str | None:
    """Convert a datetime-like value to ISO-8601 text."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def prepare_snapshot_row(
    snap: dict[str, Any],
    *,
    synced_at: datetime | None = None,
) -> dict[str, Any]:
    """Map a Postgres latest_snapshots row to Supabase stock_snapshots payload."""

    def nz(value: object) -> float:
        converted = safe_float(value)
        return 0.0 if converted is None else converted

    stamp = synced_at or datetime.now(UTC)
    return {
        "ticker_id": snap["ticker_id"],
        "ticker": snap.get("ticker"),
        "company_name": snap.get("company_name"),
        "last_price": safe_float(snap.get("last_price")),
        "last_price_ts": to_iso(snap.get("last_price_ts")),
        "price_change_pct": safe_float(snap.get("price_change_pct")),
        "price_change_abs": safe_float(snap.get("price_change_abs")),
        "high_52w": safe_float(snap.get("high_52w")),
        "low_52w": safe_float(snap.get("low_52w")),
        "volume": snap.get("volume"),
        "avg_volume_10d": snap.get("avg_volume_10d"),
        "avg_volume_30d": snap.get("avg_volume_30d"),
        "volume_ratio": safe_float(snap.get("volume_ratio")),
        "sma_10": safe_float(snap.get("sma_10")),
        "sma_20": safe_float(snap.get("sma_20")),
        "sma_50": safe_float(snap.get("sma_50")),
        "sma_100": safe_float(snap.get("sma_100")),
        "sma_200": safe_float(snap.get("sma_200")),
        "ema_10": safe_float(snap.get("ema_10")),
        "ema_20": safe_float(snap.get("ema_20")),
        "ema_50": safe_float(snap.get("ema_50")),
        "ema_200": safe_float(snap.get("ema_200")),
        "rsi_14": safe_float(snap.get("rsi_14")),
        "rsi_9": safe_float(snap.get("rsi_9")),
        "macd": safe_float(snap.get("macd")),
        "macd_signal": safe_float(snap.get("macd_signal")),
        "macd_histogram": safe_float(snap.get("macd_hist")),
        "stochastic_k": safe_float(snap.get("stochastic_k")),
        "stochastic_d": safe_float(snap.get("stochastic_d")),
        "williams_r": safe_float(snap.get("williams_r")),
        "cci": safe_float(snap.get("cci")),
        "adx": safe_float(snap.get("adx")),
        "bollinger_upper": safe_float(snap.get("bollinger_upper")),
        "bollinger_middle": safe_float(snap.get("bollinger_middle")),
        "bollinger_lower": safe_float(snap.get("bollinger_lower")),
        "pe_ratio": nz(snap.get("pe_ratio")),
        "forward_pe": nz(snap.get("forward_pe")),
        "peg_ratio": nz(snap.get("peg_ratio")),
        "price_to_book": nz(snap.get("price_to_book")),
        "price_to_sales": nz(snap.get("price_to_sales")),
        "dividend_yield": nz(snap.get("dividend_yield")),
        "market_cap": nz(snap.get("market_cap")),
        "eps": nz(snap.get("eps")),
        "eps_growth": nz(snap.get("eps_growth")),
        "revenue_growth": nz(snap.get("revenue_growth")),
        "price_vs_sma_50": safe_float(snap.get("price_vs_sma_50")),
        "price_vs_sma_200": safe_float(snap.get("price_vs_sma_200")),
        "price_vs_ema_50": safe_float(snap.get("price_vs_ema_50")),
        "price_vs_ema_200": safe_float(snap.get("price_vs_ema_200")),
        "price_vs_bollinger_middle": safe_float(snap.get("price_vs_bollinger_middle")),
        "is_bullish": snap.get("is_bullish"),
        "is_oversold": snap.get("is_oversold"),
        "is_overbought": snap.get("is_overbought"),
        "latest_signal": snap.get("latest_signal"),
        "signal_strategy": snap.get("signal_strategy"),
        "signal_confidence": safe_float(snap.get("signal_confidence")),
        "signal_timestamp": to_iso(snap.get("signal_ts")),
        "last_news_ts": to_iso(snap.get("last_news_ts")),
        "news_count_24h": snap.get("news_count_24h"),
        "updated_at": to_iso(snap.get("updated_at")),
        "synced_at": stamp.isoformat(),
    }


def upsert_stock_snapshots(
    *,
    supabase_url: str,
    service_key: str,
    rows: list[dict[str, Any]],
) -> None:
    """Upsert prepared rows to Supabase via PostgREST."""
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/stock_snapshots"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    with httpx.Client(timeout=120.0) as client:
        for offset in range(0, len(rows), BATCH_SIZE):
            batch = rows[offset : offset + BATCH_SIZE]
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    response = client.post(
                        endpoint,
                        params={"on_conflict": "ticker_id"},
                        headers=headers,
                        json=batch,
                    )
                    response.raise_for_status()
                    last_error = None
                    break
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    status = exc.response.status_code
                    if status in {522, 523, 524, 502, 503, 504} and attempt < 3:
                        import time

                        time.sleep(2.0 * attempt)
                        continue
                    if status == 522:
                        msg = (
                            "Supabase returned HTTP 522 (origin unreachable). "
                            "The project may be paused — open the Supabase dashboard "
                            "and restore/unpause the project, then retry."
                        )
                        raise RuntimeError(msg) from exc
                    raise
            if last_error is not None:
                raise last_error


def write_shadow_report(
    *,
    trade_date: date,
    canonical_count: int,
    prepared_count: int,
    sample: dict[str, Any] | None,
) -> Path:
    """Write a shadow-mode diff report for operator review."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"supabase_shadow_{trade_date.isoformat()}.md"
    lines = [
        f"# Supabase shadow report {trade_date.isoformat()}",
        "",
        "- mode: shadow",
        f"- canonical_rows: {canonical_count}",
        f"- prepared_rows: {prepared_count}",
        "",
        "Live cutover requires 3 clean shadow days and operator approval.",
        "Flip systemd ExecStart from `--shadow` to `--live`.",
    ]
    if sample:
        lines.extend(["", "## Sample row", "", "```json", json.dumps(sample, indent=2), "```"])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


class SupabaseSyncWorker(BaseWorker):
    """Publish latest_snapshots to Supabase stock_snapshots (shadow by default)."""

    worker_name = "SupabaseSyncV2"
    worker_type = "supabase_sync"
    display_name = "Supabase Sync"

    def __init__(self, *, shadow: bool = True, database_url: str | None = None) -> None:
        super().__init__(database_url=database_url)
        self.shadow = shadow

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get(
            "SUPABASE_SERVICE_ROLE_KEY",
        )
        if not url or not key:
            msg = "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set for Supabase sync"
            raise RuntimeError(msg)

        rows = await conn.fetch(FETCH_SNAPSHOTS_SQL)
        canonical_count = len(rows)
        synced_at = datetime.now(UTC)
        prepared = [prepare_snapshot_row(dict(row), synced_at=synced_at) for row in rows]
        sample = prepared[0] if prepared else None

        metadata: dict[str, Any] = {
            "trade_date": trade_date.isoformat(),
            "shadow": self.shadow or dry_run,
            "canonical_rows": canonical_count,
            "prepared_rows": len(prepared),
        }

        if self.shadow or dry_run:
            report_path = write_shadow_report(
                trade_date=trade_date,
                canonical_count=canonical_count,
                prepared_count=len(prepared),
                sample=sample,
            )
            metadata["report"] = str(report_path)
            log.info("supabase_sync_shadow_complete", **metadata)
            return WorkerResult(
                records_written=0,
                records_expected=canonical_count,
                metadata=metadata,
            )

        await asyncio.to_thread(
            upsert_stock_snapshots,
            supabase_url=url,
            service_key=key,
            rows=prepared,
        )
        metadata["synced_at"] = synced_at.isoformat()
        log.info("supabase_sync_live_complete", **metadata)
        return WorkerResult(
            records_written=len(prepared),
            records_expected=canonical_count,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    shadow = args.shadow and not args.live
    worker = SupabaseSyncWorker(shadow=shadow)
    target = date.fromisoformat(args.date) if args.date else date.today()
    result = await worker.run(target, run_type=args.run_type, dry_run=args.dry_run)
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Sync latest_snapshots to Supabase stock_snapshots",
    )
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Write to Supabase (default for systemd)",
    )
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="Shadow mode: local report only, no Supabase writes",
    )
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
