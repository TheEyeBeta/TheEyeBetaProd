"""Tests for live-trading approval gate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from broker_adapter_alpaca.live_gate import (  # noqa: E402
    LiveTradingNotApprovedError,
    assert_live_trading_allowed,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_live_gate_raises_without_approval_row() -> None:
    """Live mode startup fails when metadata.live_approval is absent."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=cur)

    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn)
    connect_cm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "broker_adapter_alpaca.live_gate.psycopg.AsyncConnection.connect",
            return_value=connect_cm,
        ),
        pytest.raises(LiveTradingNotApprovedError),
    ):
        await assert_live_trading_allowed("postgresql://test:test@localhost/db")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_live_gate_passes_with_approval_row() -> None:
    """Live mode is allowed when a live account has metadata.live_approval."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=("live-acct-1",))
    conn.execute = AsyncMock(return_value=cur)

    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn)
    connect_cm.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "broker_adapter_alpaca.live_gate.psycopg.AsyncConnection.connect",
        return_value=connect_cm,
    ):
        await assert_live_trading_allowed("postgresql://test:test@localhost/db")
