"""Universe cap-rank / cap-event service — wraps the Data API bridge with UI-friendly errors."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import structlog
from settings import Settings
from universe_control.client import fetch_cap_events, fetch_universe_active

log = structlog.get_logger()


class UniverseControlService:
    """Read-only market_cap_daily / audit_cap_events lookups for the Cap Rank/Churn pages."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_active(self, *, min_market_cap: float = 500_000_000, limit: int = 200) -> dict[str, Any]:
        try:
            payload = await fetch_universe_active(self._settings, min_market_cap=min_market_cap, limit=limit)
        except (httpx.HTTPError, RuntimeError) as exc:
            log.warning("universe_active_fetch_failed", error=str(exc)[:200])
            return {"as_of_date": None, "entries": [], "error": str(exc)[:200]}
        return {"as_of_date": payload.get("as_of_date"), "entries": payload.get("entries") or [], "error": None}

    async def get_cap_events(self, *, since: date | None = None, limit: int = 100) -> dict[str, Any]:
        try:
            payload = await fetch_cap_events(self._settings, since=since, limit=limit)
        except (httpx.HTTPError, RuntimeError) as exc:
            log.warning("cap_events_fetch_failed", error=str(exc)[:200])
            return {"events": [], "error": str(exc)[:200]}
        return {"events": payload.get("events") or [], "error": None}
