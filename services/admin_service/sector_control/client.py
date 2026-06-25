"""HTTP client for the sector_daily aggregate endpoint via the Data API bridge."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from dataapi_control.client import DataApiBridge
from settings import Settings


async def fetch_sector_daily(
    settings: Settings,
    *,
    sector: str | None = None,
    limit: int = 252,
) -> dict[str, Any]:
    """Fetch sector_daily rows from the Data API. Raises on failure — caller decides the UI fallback."""
    bridge = DataApiBridge(settings)
    if not bridge.configured():
        msg = "Cloudflare Data API bridge is not configured"
        raise RuntimeError(msg)
    params: dict[str, Any] = {"limit": limit}
    if sector:
        params["sector"] = sector
    return await bridge.get_json(f"/api/v1/sectors/daily?{urlencode(params)}", scopes=["market:read"])
