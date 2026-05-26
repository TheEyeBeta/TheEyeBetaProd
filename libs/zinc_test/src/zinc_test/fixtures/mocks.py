"""HTTP mock fixtures for external LLM and broker APIs using respx."""

from __future__ import annotations

import json
import time
from collections.abc import Generator

import httpx
import pytest
import respx


# ── Anthropic response helpers ────────────────────────────────────────────────


def _anthropic_message(text: str = "Integration test response.") -> dict[str, object]:
    return {
        "id": "msg_zinc_test_00000000",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }


# ── OpenAI response helpers ───────────────────────────────────────────────────


def _openai_completion(text: str = "Integration test response.") -> dict[str, object]:
    return {
        "id": "chatcmpl-zinc_test_00000000",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


# ── Alpaca response helpers ───────────────────────────────────────────────────


def _alpaca_account() -> dict[str, object]:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "account_number": "PA00000001",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "100000.00",
        "portfolio_value": "100000.00",
        "pattern_day_trader": False,
        "trading_blocked": False,
        "transfers_blocked": False,
        "account_blocked": False,
        "buying_power": "200000.00",
        "daytrading_buying_power": "400000.00",
        "regt_buying_power": "200000.00",
        "non_marginable_buying_power": "100000.00",
        "equity": "100000.00",
        "last_equity": "100000.00",
    }


def _alpaca_order(
    symbol: str = "AAPL",
    side: str = "buy",
    qty: str = "1",
) -> dict[str, object]:
    return {
        "id": "00000000-0000-0000-0000-000000000002",
        "client_order_id": "zinc-test-order",
        "created_at": "2025-01-15T09:30:00Z",
        "updated_at": "2025-01-15T09:30:00Z",
        "submitted_at": "2025-01-15T09:30:00Z",
        "filled_at": None,
        "expired_at": None,
        "canceled_at": None,
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": symbol,
        "asset_class": "us_equity",
        "notional": None,
        "qty": qty,
        "filled_qty": "0",
        "filled_avg_price": None,
        "order_class": "simple",
        "order_type": "market",
        "type": "market",
        "side": side,
        "time_in_force": "day",
        "limit_price": None,
        "stop_price": None,
        "status": "accepted",
        "extended_hours": False,
        "legs": None,
        "trail_percent": None,
        "trail_price": None,
        "hwm": None,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def llm_gateway_mock() -> Generator[respx.MockRouter, None, None]:
    """Intercept Anthropic and OpenAI API calls with minimal valid responses.

    Scope: function — each test gets a clean router with no recorded calls.

    Usage::

        def test_something(llm_gateway_mock):
            # All httpx requests to api.anthropic.com and api.openai.com
            # are intercepted automatically.
            ...

    Customise a specific route inside your test::

        llm_gateway_mock["anthropic_messages"].mock(
            return_value=httpx.Response(200, json={...})
        )
    """
    with respx.mock(assert_all_called=False) as router:
        router.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                content=json.dumps(_anthropic_message()).encode(),
                headers={"content-type": "application/json"},
            ),
        ).name = "anthropic_messages"

        router.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=json.dumps(_openai_completion()).encode(),
                headers={"content-type": "application/json"},
            ),
        ).name = "openai_chat_completions"

        # LiteLLM proxy (used by llm-gateway service in local dev)
        router.post(url__regex=r"http://llm-gateway[^/]*/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=json.dumps(_openai_completion()).encode(),
                headers={"content-type": "application/json"},
            ),
        ).name = "litellm_proxy_chat"

        yield router


@pytest.fixture
def alpaca_mock() -> Generator[respx.MockRouter, None, None]:
    """Intercept Alpaca paper API calls with minimal valid responses.

    Scope: function — each test gets a clean router.

    Routes registered:

    * ``GET  /v2/account``   → paper account stub
    * ``GET  /v2/orders``    → empty order list
    * ``POST /v2/orders``    → accepted order stub
    * ``GET  /v2/positions`` → empty positions list
    * ``GET  /v2/clock``     → market-open clock stub
    * ``GET  /v2/assets/AAPL`` → AAPL asset stub

    Usage::

        def test_place_order(alpaca_mock):
            alpaca_mock["alpaca_post_orders"].mock(
                return_value=httpx.Response(200, json={...})
            )
            ...
    """
    _base = "https://paper-api.alpaca.markets"

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{_base}/v2/account").mock(
            return_value=httpx.Response(200, json=_alpaca_account()),
        ).name = "alpaca_get_account"

        router.get(f"{_base}/v2/orders").mock(
            return_value=httpx.Response(200, json=[]),
        ).name = "alpaca_get_orders"

        router.post(f"{_base}/v2/orders").mock(
            return_value=httpx.Response(200, json=_alpaca_order()),
        ).name = "alpaca_post_orders"

        router.delete(url__regex=rf"{_base}/v2/orders/.*").mock(
            return_value=httpx.Response(204),
        ).name = "alpaca_cancel_order"

        router.get(f"{_base}/v2/positions").mock(
            return_value=httpx.Response(200, json=[]),
        ).name = "alpaca_get_positions"

        router.get(f"{_base}/v2/clock").mock(
            return_value=httpx.Response(
                200,
                json={
                    "timestamp": "2025-01-15T09:30:00-05:00",
                    "is_open": True,
                    "next_open": "2025-01-16T09:30:00-05:00",
                    "next_close": "2025-01-15T16:00:00-05:00",
                },
            ),
        ).name = "alpaca_get_clock"

        router.get(f"{_base}/v2/assets/AAPL").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
                    "class": "us_equity",
                    "exchange": "NASDAQ",
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "status": "active",
                    "tradable": True,
                    "marginable": True,
                    "shortable": True,
                    "easy_to_borrow": True,
                    "fractionable": True,
                },
            ),
        ).name = "alpaca_get_asset_aapl"

        yield router
