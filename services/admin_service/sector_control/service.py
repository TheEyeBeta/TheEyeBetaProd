"""Sector aggregate service — wraps the Data API bridge with UI-friendly errors."""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from sector_control.client import fetch_sector_daily
from settings import Settings

log = structlog.get_logger()


class SectorControlService:
    """Read-only sector_daily lookups for the Rotation/Breadth/Performance pages."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_daily(self, *, sector: str | None = None, limit: int = 252) -> dict[str, Any]:
        try:
            payload = await fetch_sector_daily(self._settings, sector=sector, limit=limit)
        except (httpx.HTTPError, RuntimeError) as exc:
            log.warning("sector_daily_fetch_failed", error=str(exc)[:200])
            return {"sectors": [], "error": str(exc)[:200]}
        return {"sectors": payload.get("sectors") or [], "error": None}
