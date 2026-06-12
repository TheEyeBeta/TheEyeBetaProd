from __future__ import annotations

from datetime import date

import pytest

from workers.massive_providers import (
    DailyBar,
    UniverseInstrument,
    classify_coverage,
    parse_massive_grouped,
    pick_spot_check_symbols,
    provider_chain_plan,
    validate_bar,
)


def _inst(symbol: str, instrument_id: int = 1) -> UniverseInstrument:
    return UniverseInstrument(
        instrument_id=instrument_id,
        ticker_id=instrument_id,
        symbol=symbol,
        exchange_code="XNAS",
    )


def test_classify_coverage_thresholds() -> None:
    assert classify_coverage(500, 501) == "ok"
    assert classify_coverage(490, 501) == "warn"
    assert classify_coverage(470, 501) == "fail"


def test_validate_bar_rejects_invalid_ohlc() -> None:
    reason = validate_bar(
        symbol="AAPL",
        open_=0.0,
        high=10.0,
        low=9.0,
        close=10.0,
        volume=100,
        prev_close=9.5,
        has_corporate_action=False,
    )
    assert reason is not None
    assert "non-positive" in reason


def test_validate_bar_rejects_large_move_without_corp_action() -> None:
    reason = validate_bar(
        symbol="XYZ",
        open_=100.0,
        high=140.0,
        low=95.0,
        close=130.0,
        volume=1_000,
        prev_close=100.0,
        has_corporate_action=False,
    )
    assert reason is not None
    assert "exceeds 25%" in reason


def test_validate_bar_allows_large_move_with_corp_action() -> None:
    assert (
        validate_bar(
            symbol="XYZ",
            open_=100.0,
            high=140.0,
            low=95.0,
            close=130.0,
            volume=1_000,
            prev_close=100.0,
            has_corporate_action=True,
        )
        is None
    )


def test_provider_chain_plan_prefers_massive() -> None:
    universe = [_inst("AAPL", 1), _inst("MSFT", 2), _inst("ZZZ", 3)]
    massive = {
        "AAPL": DailyBar(1, "AAPL", date(2026, 6, 10), 1, 2, 1, 1.5, 1.5, 100, "massive"),
        "MSFT": DailyBar(2, "MSFT", date(2026, 6, 10), 1, 2, 1, 1.5, 1.5, 100, "massive"),
    }
    plan = provider_chain_plan(universe, massive)
    assert plan[0] == (universe[0], "massive")
    assert plan[1] == (universe[1], "massive")
    assert plan[2] == (universe[2], "finnhub")


def test_parse_massive_grouped_filters_to_universe() -> None:
    universe = {"AAPL": _inst("AAPL", 10), "MSFT": _inst("MSFT", 11)}
    payload = {
        "results": [
            {"T": "AAPL", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 100},
            {"T": "UNKNOWN", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 100},
        ],
    }
    bars = parse_massive_grouped(payload, symbol_map=universe, trade_date=date(2026, 6, 10))
    assert set(bars) == {"AAPL"}
    assert bars["AAPL"].source == "massive"


def test_pick_spot_check_symbols_prefers_liquid_names() -> None:
    symbols = pick_spot_check_symbols({"AAPL", "MSFT", "ZZZ", "QQQ"})
    assert symbols[:2] == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_non_trading_day_skips_without_writes() -> None:
    from workers.massive_ingestion_worker import (
        MassiveDailyIngestionWorker,
        resolve_target_trade_date,
    )

    class FakeConn:
        async def fetchval(self, *_args: object, **_kwargs: object) -> bool:
            return False

    assert await resolve_target_trade_date(FakeConn(), date(2026, 6, 7)) is None

    class FakeWorker(MassiveDailyIngestionWorker):
        async def execute(self, conn, trade_date, *, dry_run: bool):  # noqa: ANN001
            target = await resolve_target_trade_date(conn, trade_date)
            assert target is None
            from workers.base_worker import WorkerResult

            return WorkerResult(metadata={"note": "non-trading day", "skipped": True})

    worker = FakeWorker(database_url="postgresql://unused")
    result = await worker.execute(FakeConn(), date(2026, 6, 7), dry_run=False)
    assert result.metadata["note"] == "non-trading day"
