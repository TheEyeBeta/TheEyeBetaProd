"""HTTP client for the universe cap-rank and cap-event endpoints via the Data API bridge."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlencode

from dataapi_control.client import DataApiBridge
from settings import Settings


async def fetch_universe_active(
    settings: Settings,
    *,
    min_market_cap: float = 500_000_000,
    limit: int = 200,
) -> dict[str, Any]:
    """Fetch the latest active-universe cap rankings. Raises on failure — caller decides the UI fallback."""
    bridge = DataApiBridge(settings)
    if not bridge.configured():
        msg = "Cloudflare Data API bridge is not configured"
        raise RuntimeError(msg)
    params: dict[str, Any] = {"min_market_cap": min_market_cap, "limit": limit}
    return await bridge.get_json(f"/api/v1/universe/active?{urlencode(params)}", scopes=["market:read"])


async def fetch_cap_events(
    settings: Settings,
    *,
    since: date | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Fetch universe cap-change events. Raises on failure — caller decides the UI fallback."""
    bridge = DataApiBridge(settings)
    if not bridge.configured():
        msg = "Cloudflare Data API bridge is not configured"
        raise RuntimeError(msg)
    params: dict[str, Any] = {"limit": limit}
    if since:
        params["since"] = since.isoformat()
    return await bridge.get_json(f"/api/v1/universe/cap-events?{urlencode(params)}", scopes=["market:read"])
