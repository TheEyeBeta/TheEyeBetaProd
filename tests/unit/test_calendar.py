"""Unit tests for trading calendar helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from workers.calendar import is_trading_day, resolve_trading_day_on_or_before


async def test_is_trading_day_weekday_fallback() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    assert await is_trading_day(conn, date(2026, 6, 15)) is True


async def test_resolve_trading_day_raises_when_empty() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    with pytest.raises(RuntimeError, match="trading day"):
        await resolve_trading_day_on_or_before(conn, date(2026, 6, 15))
