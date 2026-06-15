"""Unit tests for two-tier universe helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from workers.market_cap_providers import CAP_THRESHOLD_USD, action_for_event
from workers.universe_tiers import (
    CAP_INTRADAY_THRESHOLD_USD,
    load_intraday_universe,
    resolve_latest_cap_date,
)


def test_intraday_threshold_matches_cap_constant() -> None:
    assert CAP_INTRADAY_THRESHOLD_USD == CAP_THRESHOLD_USD


def test_action_for_event_intraday_tier_labels() -> None:
    assert action_for_event("CROSSED_UP") == "ADD_TO_INTRADAY"
    assert action_for_event("CROSSED_DOWN") == "REMOVE_FROM_INTRADAY"


async def test_resolve_latest_cap_date() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=date(2026, 6, 12))
    assert await resolve_latest_cap_date(conn, date(2026, 6, 13)) == date(2026, 6, 12)


async def test_resolve_latest_cap_date_raises_when_empty() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    with pytest.raises(RuntimeError, match="market_cap_daily"):
        await resolve_latest_cap_date(conn, date.today())


async def test_load_intraday_universe_filters_by_cap() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=date(2026, 6, 12))
    conn.fetch = AsyncMock(
        return_value=[
            {
                "instrument_id": 1,
                "ticker_id": 10,
                "symbol": "BIGCO",
                "exchange_code": "XNYS",
            },
        ],
    )
    universe = await load_intraday_universe(conn)
    assert len(universe) == 1
    assert universe[0].symbol == "BIGCO"
    query = conn.fetch.await_args.args[0]
    assert "market_cap >= $2" in query
    assert conn.fetch.await_args.args[2] == CAP_INTRADAY_THRESHOLD_USD
