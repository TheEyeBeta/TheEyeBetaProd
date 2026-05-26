"""Unit tests for TradeUpdateStreamer NATS publishing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from broker_adapter_alpaca.adapter import AlpacaAdapter  # noqa: E402
from broker_adapter_alpaca.settings import Settings  # noqa: E402
from broker_adapter_alpaca.streamer import TradeUpdateStreamer  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamer_publishes_fill_event_to_nats() -> None:
    """fill events are published on broker.fills.{order_id} with full payload."""
    adapter = AlpacaAdapter(Settings(mode="paper", database_url="postgresql://x/x"))
    streamer = TradeUpdateStreamer(adapter, "nats://127.0.0.1:4222")
    streamer._nc = MagicMock()
    streamer._nc.publish = AsyncMock()

    event = {
        "order_id": "660e8400-e29b-41d4-a716-446655440099",
        "event": "fill",
        "qty": 1.0,
        "price": 100.0,
        "status": "filled",
        "order": {"id": "alpaca-1"},
        "raw": {"event": "fill"},
    }
    await streamer._on_trade_update(event)

    streamer._nc.publish.assert_awaited_once()
    subject, payload_bytes = streamer._nc.publish.await_args[0]
    assert subject == "broker.fills.660e8400-e29b-41d4-a716-446655440099"
    published = json.loads(payload_bytes.decode())
    assert published["event"] == "fill"
    assert published["order"]["id"] == "alpaca-1"
