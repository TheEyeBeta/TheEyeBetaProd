"""HTTP client for broker-adapter-alpaca."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger()


class BrokerAdapterClient:
    """Fetch broker-side positions and orders for reconciliation."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def list_positions(self) -> list[dict[str, Any]]:
        """Return normalized positions from the broker adapter."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self._base_url}/v1/positions")
            response.raise_for_status()
            body = response.json()
        return list(body.get("positions") or [])

    async def list_orders(self) -> list[dict[str, Any]]:
        """Return normalized orders from the broker adapter."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self._base_url}/v1/orders")
            response.raise_for_status()
            body = response.json()
        return list(body.get("orders") or [])
