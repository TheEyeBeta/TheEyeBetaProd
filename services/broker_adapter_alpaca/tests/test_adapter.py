"""Unit tests for AlpacaAdapter."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zinc_schemas.broker_base import SubmitOrderRequest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from broker_adapter_alpaca.adapter import (  # noqa: E402
    AlpacaAdapter,
    normalize_trade_update,
)
from broker_adapter_alpaca.settings import Settings  # noqa: E402


@pytest.mark.unit
def test_submit_order_registers_uuidv7_client_mapping() -> None:
    """submit_order assigns UUIDv7 client_order_id and maps internal order id."""
    settings = Settings(
        mode="paper",
        database_url="postgresql://test:test@localhost/db",
    )
    adapter = AlpacaAdapter(settings)

    placed = MagicMock()
    placed.id = "alpaca-1"
    placed.client_order_id = "cid-1"
    placed.symbol = "AAPL"
    placed.side = MagicMock(value="buy")
    placed.qty = 1
    placed.filled_qty = 0
    placed.status = MagicMock(value="accepted")
    placed.filled_avg_price = 0

    with patch.object(adapter, "_client") as mock_client:
        mock_client.return_value.submit_order.return_value = placed
        result = adapter.submit_order(
            SubmitOrderRequest(
                order_id="660e8400-e29b-41d4-a716-446655440099",
                symbol="AAPL",
                side="buy",
                qty=1.0,
            ),
        )

    assert result.order_id == "660e8400-e29b-41d4-a716-446655440099"
    assert len(result.client_order_id) == 36
    assert adapter.resolve_order_id(result.client_order_id) == result.order_id


@pytest.mark.unit
async def test_normalize_trade_update_builds_nats_payload() -> None:
    """Trade updates include order_id routing and full event envelope."""
    adapter = AlpacaAdapter(Settings(mode="paper", database_url="postgresql://x/x"))
    adapter.register_order_mapping("order-abc", "client-xyz", "zinc")

    event = {
        "event": "fill",
        "order": {
            "id": "alpaca-99",
            "client_order_id": "client-xyz",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "filled_qty": 1,
            "status": "filled",
            "filled_avg_price": 190.5,
        },
    }
    normalized = await normalize_trade_update(event, adapter)

    assert normalized["order_id"] == "order-abc"
    assert normalized["event"] == "fill"
    assert normalized["qty"] == 1.0
    assert normalized["price"] == 190.5
    assert normalized["order"]["symbol"] == "AAPL"
    assert normalized["raw"] == event


@pytest.mark.unit
async def test_normalize_trade_update_falls_back_to_db_after_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart-wiped in-memory map is recovered via the persisted client_order_id."""
    adapter = AlpacaAdapter(Settings(mode="paper", database_url="postgresql://x/x"))

    async def fake_resolve(self: AlpacaAdapter, client_order_id: str) -> str | None:
        assert client_order_id == "client-xyz"
        return "order-from-db"

    monkeypatch.setattr(AlpacaAdapter, "resolve_order_id_durable", fake_resolve)

    event = {
        "event": "fill",
        "order": {"id": "alpaca-99", "client_order_id": "client-xyz", "filled_qty": 1},
    }
    normalized = await normalize_trade_update(event, adapter)

    assert normalized["order_id"] == "order-from-db"
