"""BacktestRunner — orchestrates data, decisions, and zinc_native.bt.Engine."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from backtest_engine.db import (
    insert_backtest_run,
    insert_metrics,
    update_run_status,
    update_run_universe,
)
from backtest_engine.decisions import (
    DecisionFn,
    StrategyContext,
    build_redecision_book,
    load_replay_decisions,
    load_strategy,
    make_strategy_callback,
)
from backtest_engine.metrics import compute_metrics
from backtest_engine.parquet import build_parquet, write_pnl_parquet
from backtest_engine.settings import Settings
from backtest_engine.storage import upload_file
from backtest_engine.universe import union_universe
from backtest_engine.validation import guard_decision_callback, guard_engine_strategy
from backtest_engine.walk_forward import iter_windows, parse_walk_forward
from zinc_native import bt

log = structlog.get_logger()


@dataclass
class RunConfig:
    """Parameters for one backtest execution."""

    strategy_id: str
    start_date: date
    end_date: date
    universe: str | None = None
    walk_forward: bool | None = None
    mode: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    run_id: UUID | None = None


@dataclass
class RunResult:
    """Summary returned after a completed run."""

    backtest_id: UUID
    status: str
    metrics: dict[str, float]
    result_blob_uri: str | None
    elapsed_seconds: float


def _default_slippage() -> bt.SlippageModel:
    """Slippage + implicit commission via participation curve."""
    return bt.SlippageModel(
        lambda atr, participation: min(0.0005 * max(atr, 1.0) + 0.0001 * abs(participation), 0.02),
    )


class BacktestRunner:
    """Execute backtests against Postgres, MinIO, and the C++ engine."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    async def run(self, config: RunConfig) -> RunResult:
        """Run a full backtest asynchronously."""
        started = time.perf_counter()
        dsn = self._settings.pg_dsn()
        ctx = await load_strategy(dsn, config.strategy_id)
        if config.mode:
            ctx = StrategyContext(
                strategy_id=ctx.strategy_id,
                market=ctx.market,
                max_positions=ctx.max_positions,
                agent_id=ctx.agent_id,
                mode=config.mode,
            )

        wf_payload: dict[str, Any] | bool
        if config.walk_forward is None:
            wf_payload = config.config.get("walk_forward") or {"enabled": False}
        else:
            wf_payload = {"enabled": config.walk_forward}
        run_config = {**config.config, "mode": ctx.mode, "walk_forward": wf_payload}
        wf = parse_walk_forward(run_config)

        symbols = await union_universe(
            dsn,
            market=ctx.market,
            start=config.start_date,
            end=config.end_date,
            explicit_universe=config.universe,
        )
        if not symbols:
            symbols = ["SPY", "AAPL", "MSFT"]

        blob_uri: str | None = None
        if config.run_id is not None:
            run_id = config.run_id
            await update_run_universe(
                dsn,
                run_id,
                universe=",".join(symbols),
                config=run_config,
            )
        else:
            run_id = await insert_backtest_run(
                dsn,
                strategy_id=config.strategy_id,
                start_date=config.start_date,
                end_date=config.end_date,
                universe=",".join(symbols),
                config=run_config,
                git_sha=self._settings.git_sha,
            )

        try:
            combined_pnl: list[float] = []
            combined_dates: list[str] = []
            total_turnover = 0.0
            max_dd = 0.0

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                market_parquet = tmp_path / "market.parquet"
                await build_parquet(
                    dsn,
                    symbols=symbols,
                    start=config.start_date,
                    end=config.end_date,
                    output_path=market_parquet,
                )

                windows = iter_windows(config.start_date, config.end_date, wf)
                for window in windows:
                    if ctx.mode == "redecision":
                        trade_dates = _dates_between(window.test_start, window.test_end)
                        book = await build_redecision_book(
                            dsn,
                            ctx,
                            start=window.train_start,
                            end=window.test_end,
                            trade_dates=trade_dates,
                        )
                    else:
                        book = await load_replay_decisions(
                            dsn,
                            market=ctx.market,
                            start=window.test_start,
                            end=window.test_end,
                        )

                    callback = guard_decision_callback(
                        book,
                        make_strategy_callback(book, max_positions=ctx.max_positions),
                    )
                    result = _run_engine(
                        config.strategy_id,
                        window.test_start,
                        window.test_end,
                        symbols,
                        market_parquet,
                        callback,
                        decision_book=book,
                    )
                    combined_pnl.extend([float(v) for v in result.daily_pnl])
                    combined_dates.extend(
                        _dates_between(window.test_start, window.test_end)[: len(result.daily_pnl)],
                    )
                    total_turnover += float(result.metrics.turnover)
                    max_dd = max(max_dd, float(result.metrics.max_drawdown))

                metrics = compute_metrics(
                    combined_pnl,
                    max_drawdown=max_dd,
                    turnover=total_turnover / max(len(windows), 1),
                )
                await insert_metrics(dsn, run_id, metrics.as_rows())

                pnl_path = tmp_path / "pnl.parquet"
                if not combined_dates:
                    combined_dates = [config.start_date.isoformat()] * len(combined_pnl)
                write_pnl_parquet(
                    trade_dates=combined_dates[: len(combined_pnl)],
                    daily_pnl=combined_pnl,
                    output_path=pnl_path,
                )
                blob_uri = upload_file(
                    self._settings,
                    local_path=pnl_path,
                    object_key=f"{run_id}/pnl.parquet",
                )
                await update_run_status(dsn, run_id, status="succeeded", result_blob_uri=blob_uri)

        except Exception as exc:  # noqa: BLE001
            log.exception("backtest_run_failed", backtest_id=str(run_id), error=str(exc))
            await update_run_status(dsn, run_id, status="failed")
            raise

        elapsed = time.perf_counter() - started
        log.info(
            "backtest_run_complete",
            backtest_id=str(run_id),
            elapsed_seconds=round(elapsed, 3),
        )
        return RunResult(
            backtest_id=run_id,
            status="succeeded",
            metrics=dict(metrics.as_rows()),
            result_blob_uri=blob_uri,
            elapsed_seconds=elapsed,
        )


def _run_engine(
    strategy_id: str,
    start: date,
    end: date,
    universe: list[str],
    parquet_path: Path,
    decision_callback: DecisionFn,
    *,
    decision_book: object | None = None,
    prices_by_date: dict[str, list[float]] | None = None,
) -> bt.Result:
    """Invoke the C++ engine for one calendar window."""
    engine = bt.Engine(
        strategy_id,
        start.isoformat(),
        end.isoformat(),
        universe,
        _default_slippage(),
    )
    engine.set_parquet_path(str(parquet_path))
    if prices_by_date is not None and hasattr(engine, "_price_by_date"):
        engine._price_by_date = prices_by_date  # type: ignore[attr-defined]

    def strategy(snapshot: bt.Snapshot) -> bt.Decision:
        symbol_names = list(snapshot.symbol_names)
        idx, weight = decision_callback(
            snapshot.trade_date,
            symbol_names,
            snapshot.day_index,
        )
        return bt.Decision(symbol_index=idx, target_weight=weight)

    if decision_book is not None:
        engine.set_strategy(guard_engine_strategy(decision_book, strategy))
    else:
        engine.set_strategy(strategy)
    return engine.run()


def _dates_between(start: date, end: date) -> list[str]:
    """Inclusive ISO date list (weekdays not filtered — engine skips missing days)."""
    from datetime import timedelta

    out: list[str] = []
    day = start
    while day <= end:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out
