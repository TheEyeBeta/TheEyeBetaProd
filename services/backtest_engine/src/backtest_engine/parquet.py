"""Build daily Parquet datasets for zinc_native.bt.Engine."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

log = structlog.get_logger()

_PARQUET_COLUMNS = (
    "trade_date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "atr14",
    "adv",
)


async def build_parquet(
    dsn: str,
    *,
    symbols: list[str],
    start: date,
    end: date,
    output_path: Path,
) -> Path:
    """Export ``prices_daily`` rows into engine-compatible Parquet.

    Args:
        dsn: Postgres DSN.
        symbols: Universe symbols.
        start: Inclusive start date.
        end: Inclusive end date.
        output_path: Destination ``.parquet`` file.

    Returns:
        Path to the written file.
    """
    if not symbols:
        msg = "cannot build parquet for empty universe"
        raise ValueError(msg)

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT p.ts::date AS trade_date,
                   i.symbol,
                   p.open,
                   p.high,
                   p.low,
                   p.close,
                   p.volume
              FROM theeyebeta.prices_daily p
              JOIN theeyebeta.instruments i ON i.id = p.instrument_id
             WHERE i.symbol = ANY(%s)
               AND p.ts::date BETWEEN %s AND %s
             ORDER BY p.ts, i.symbol
            """,
            (symbols, start, end),
        )
        rows = await cur.fetchall()

    if not rows:
        log.warning("parquet_no_db_rows_using_synthetic", symbols=len(symbols))
        rows = _synthetic_rows(symbols, start, end)

    by_symbol: dict[str, list[tuple]] = {}
    for row in rows:
        symbol = str(row[1])
        by_symbol.setdefault(symbol, []).append(row)

    out_rows: list[dict[str, object]] = []
    for symbol, sym_rows in by_symbol.items():
        atr_state = _AtrState()
        for trade_date, _, open_, high, low, close, volume in sym_rows:
            atr14 = atr_state.update(float(high), float(low), float(close))
            adv = float(volume) * float(close)
            out_rows.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "symbol": symbol,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                    "atr14": atr14,
                    "adv": adv,
                },
            )

    table = pa.Table.from_pylist(out_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)
    log.info("parquet_built", path=str(output_path), rows=len(out_rows))
    return output_path


def write_pnl_parquet(
    *,
    trade_dates: list[str],
    daily_pnl: list[float],
    output_path: Path,
) -> Path:
    """Write daily PnL series for MinIO upload."""
    table = pa.Table.from_pydict(
        {
            "trade_date": trade_dates,
            "pnl": daily_pnl,
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)
    return output_path


class _AtrState:
    """Rolling ATR(14) for Parquet enrichment."""

    def __init__(self) -> None:
        self._prev_close: float | None = None
        self._trs: list[float] = []

    def update(self, high: float, low: float, close: float) -> float:
        """Append one bar and return current ATR."""
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self._trs.append(tr)
        window = self._trs[-14:]
        return sum(window) / len(window)


def _synthetic_rows(
    symbols: list[str],
    start: date,
    end: date,
) -> list[tuple]:
    """Generate deterministic price paths when DB has no rows (tests/smoke)."""
    from datetime import timedelta

    rows: list[tuple] = []
    day = start
    day_index = 0
    while day <= end:
        for symbol in symbols:
            base = 100.0 + day_index * 0.05 + hash(symbol) % 20
            close = base * (1.0001**day_index)
            rows.append(
                (
                    day,
                    symbol,
                    close,
                    close * 1.001,
                    close * 0.999,
                    close,
                    1_000_000.0,
                ),
            )
        day += timedelta(days=1)
        day_index += 1
    return rows
