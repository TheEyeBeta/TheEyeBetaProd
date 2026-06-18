"""Broker adapter protocol and shared order contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SubmitOrderRequest(BaseModel):
    """Normalized order submission request."""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    symbol: str
    side: str
    qty: float = Field(gt=0)
    order_type: str = "market"
    account: str = "zinc"  # sub-account: "zinc" | "nyse" | "nasdaq"


class SubmitOrderResult(BaseModel):
    """Broker acknowledgement after order submission."""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    qty: float
    status: str
    account: str = "zinc"
    raw: dict[str, Any] = Field(default_factory=dict)


TradeUpdateHandler = Callable[[dict[str, Any]], Awaitable[None]]


@runtime_checkable
class BrokerAdapter(Protocol):
    """Interface implemented by venue-specific broker adapters."""

    def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit an order to the broker."""
        ...

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        """Cancel an open broker order by Alpaca order id."""
        ...

    def list_positions(self) -> list[dict[str, Any]]:
        """Return open positions normalized for reconciliation."""
        ...

    def list_orders(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent orders normalized for reconciliation."""
        ...

    async def stream_trade_updates(self, handler: TradeUpdateHandler) -> None:
        """Stream trade lifecycle events until stopped."""
        ...
