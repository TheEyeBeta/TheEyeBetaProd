"""Unit tests for ApprovedOrderConsumer order-submission handling."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from broker_adapter_alpaca.adapter import AlpacaAdapter  # noqa: E402
from broker_adapter_alpaca.consumer import ApprovedOrderConsumer  # noqa: E402
from broker_adapter_alpaca.settings import Settings  # noqa: E402


def _fake_msg(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.data = json.dumps(payload).encode()
    return msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_marks_order_rejected_when_broker_rejects_submission() -> None:
    """A broker-side rejection (e.g. insufficient buying power) marks the order
    'rejected' in Postgres instead of leaving it stuck at 'submitted' forever."""
    settings = Settings(mode="paper", database_url="postgresql://test:test@localhost/db")
    adapter = AlpacaAdapter(settings)
    consumer = ApprovedOrderConsumer(settings, adapter, symbol_resolver={1: "AAPL"})

    with (
        patch(
            "broker_adapter_alpaca.consumer.assert_order_submission_allowed",
            AsyncMock(),
        ),
        patch.object(
            adapter,
            "submit_order",
            side_effect=RuntimeError("insufficient buying power"),
        ),
        patch.object(consumer, "_mark_rejected", AsyncMock()) as mock_reject,
        patch.object(consumer, "_persist_submission", AsyncMock()) as mock_persist,
    ):
        await consumer._handle(
            _fake_msg(
                {
                    "order_id": "order-1",
                    "instrument_id": 1,
                    "side": "buy",
                    "qty": 1.0,
                },
            ),
        )

    mock_reject.assert_awaited_once_with("order-1")
    mock_persist.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_rejected_updates_order_status() -> None:
    """_mark_rejected issues the rejected-status UPDATE against Postgres."""
    settings = Settings(mode="paper", database_url="postgresql://test:test@localhost/db")
    adapter = AlpacaAdapter(settings)
    consumer = ApprovedOrderConsumer(settings, adapter)

    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn)
    connect_cm.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "broker_adapter_alpaca.consumer.psycopg.AsyncConnection.connect",
        return_value=connect_cm,
    ):
        await consumer._mark_rejected("order-1")

    conn.execute.assert_awaited_once()
    args = conn.execute.await_args[0]
    assert "status = 'rejected'" in args[0]
    assert args[1] == ("order-1",)
    conn.commit.assert_awaited_once()
