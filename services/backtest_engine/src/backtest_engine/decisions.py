"""Decision providers for replay and re-decision modes."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import psycopg
import structlog

log = structlog.get_logger()

DecisionFn = Callable[[str, list[str], int], tuple[int, float]]


@dataclass
class StrategyContext:
    """Parsed strategy configuration."""

    strategy_id: str
    market: str
    max_positions: int = 10
    agent_id: str = "technical-analyst"
    mode: str = "replay"


@dataclass
class DecisionBook:
    """Point-in-time decisions keyed by trade date."""

    by_date: dict[str, dict[str, float]] = field(default_factory=dict)

    def weight(self, trade_date: str, symbol: str) -> float:
        """Return target weight for symbol on date (0 when absent)."""
        return self.by_date.get(trade_date, {}).get(symbol, 0.0)


async def load_strategy(dsn: str, strategy_id: str) -> StrategyContext:
    """Load strategy row from Postgres."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT config
              FROM theeyebeta.strategies
             WHERE id = %s
            """,
            (strategy_id,),
        )
        row = await cur.fetchone()
    if row is None:
        msg = f"strategy {strategy_id} not found"
        raise ValueError(msg)
    config = row[0] if isinstance(row[0], dict) else {}
    return StrategyContext(
        strategy_id=strategy_id,
        market=str(config.get("market", "US.NASDAQ")),
        max_positions=int(config.get("max_positions", 10)),
        agent_id=str(config.get("agent_id", "technical-analyst")),
        mode=str(config.get("mode", "replay")),
    )


async def load_replay_decisions(
    dsn: str,
    *,
    market: str,
    start: date,
    end: date,
) -> DecisionBook:
    """Load historical ``agent_decisions`` verbatim (frozen per decision date)."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT ar.started_at::date AS decision_date,
                   i.symbol,
                   ad.decision,
                   ad.confidence
              FROM theeyebeta.agent_decisions ad
              JOIN theeyebeta.agent_runs ar ON ar.id = ad.run_id
              LEFT JOIN theeyebeta.instruments i ON i.id = ad.instrument_id
             WHERE ad.market = %s
               AND ar.started_at::date BETWEEN %s AND %s
               AND i.symbol IS NOT NULL
            """,
            (market, start, end),
        )
        rows = await cur.fetchall()

    book = DecisionBook()
    pending: dict[str, list[tuple[str, float]]] = {}
    for decision_date, symbol, decision, confidence in rows:
        key = decision_date.isoformat()
        if str(decision).upper() not in {"BUY", "REDUCE"}:
            continue
        pending.setdefault(key, []).append((str(symbol), float(confidence)))

    for key, entries in pending.items():
        entries.sort(key=lambda item: item[1], reverse=True)
        weight = 1.0 / max(len(entries), 1)
        book.by_date[key] = {symbol: weight for symbol, _ in entries[:10]}

    log.info("replay_decisions_loaded", days=len(book.by_date))
    return book


async def build_redecision_book(
    dsn: str,
    ctx: StrategyContext,
    *,
    start: date,
    end: date,
    trade_dates: list[str],
) -> DecisionBook:
    """Re-run agent_runtime per day with frozen ``SOURCE_DATE``."""
    from agent_runtime.runner import run_agent  # noqa: PLC0415

    book = DecisionBook()
    for trade_date in trade_dates:
        os.environ["SOURCE_DATE"] = trade_date
        try:
            await run_agent(ctx.agent_id, ctx.market.split(".")[0], trade_date)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "redecision_agent_failed",
                trade_date=trade_date,
                error=str(exc),
            )
        day_book = await load_replay_decisions(
            dsn,
            market=ctx.market,
            start=date.fromisoformat(trade_date),
            end=date.fromisoformat(trade_date),
        )
        book.by_date.update(day_book.by_date)
        await _clear_agent_memory(dsn, ctx.agent_id)
    return book


async def _clear_agent_memory(dsn: str, agent_id: str) -> None:
    """Clear agent memory between walk-forward iterations."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            "DELETE FROM theeyebeta.agent_memory WHERE agent_id = %s",
            (agent_id,),
        )
        await conn.commit()


def make_strategy_callback(
    book: DecisionBook,
    *,
    max_positions: int,
    fallback_symbol_index: int = 0,
) -> DecisionFn:
    """Build a callable consumed by the C++ engine strategy bridge."""

    def _callback(trade_date: str, symbols: list[str], day_index: int) -> tuple[int, float]:
        weights = book.by_date.get(trade_date, {})
        if not weights:
            return fallback_symbol_index, 1.0 if day_index == 0 else 0.0

        ranked = sorted(
            ((idx, symbols[idx], weights.get(symbols[idx], 0.0)) for idx in range(len(symbols))),
            key=lambda item: item[2],
            reverse=True,
        )
        for idx, _symbol, weight in ranked[:max_positions]:
            if weight > 0:
                return idx, min(weight, 1.0)
        return fallback_symbol_index, 0.0

    return _callback
