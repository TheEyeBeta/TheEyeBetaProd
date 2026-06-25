"""Terminal Echo market-data proxy backed by the Cloudflare Data API."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import structlog
from auth import CurrentUser
from dataapi_control.client import DataApiBridge
from deps import SettingsDep
from fastapi import APIRouter, HTTPException, Query, Request, status
from frontend_ia.modules import TERMINAL_MODULES
from frontend_ia.nav import normalize_user_roles, user_has_role
from settings import Settings
from slowapi import Limiter

log = structlog.get_logger()

router = APIRouter(prefix="/terminal-data", tags=["terminal-data"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9.^:_-]{1,24}$")
_INDICATOR_KINDS = frozenset({"technical", "risk", "returns", "valuation"})
_registered = False

MARKET_SURFACES: tuple[dict[str, object], ...] = (
    {
        "key": "full-universe-screener",
        "title": "Full-Universe Screener",
        "status": "partial",
        "href": "/admin/universe/screener",
        "ready": "Indicator routes are live for searchable tickers.",
        "blocked_by": "Sector, asset_class, and market_cap need universe wiring.",
        "endpoints": [
            "/api/v1/indicators/{ticker}/technical",
            "/api/v1/indicators/{ticker}/risk",
            "/api/v1/indicators/{ticker}/returns",
            "/api/v1/indicators/{ticker}/valuation",
            "/api/v1/symbols/search",
        ],
    },
    {
        "key": "sector-rotation",
        "title": "Sector Rotation Heatmap",
        "status": "planned",
        "href": "/admin/sectors/rotation",
        "ready": "sector_daily table is backfilled.",
        "blocked_by": "Needs GET /api/v1/sectors/daily or allowlisted table rows.",
        "endpoints": ["/api/v1/sectors/daily"],
    },
    {
        "key": "sector-breadth",
        "title": "Sector Breadth Dashboard",
        "status": "planned",
        "href": "/admin/sectors/breadth",
        "ready": "Breadth fields exist in sector_daily.",
        "blocked_by": "Needs DataAPI exposure for pct_above_sma_50/200 and median_rsi_14.",
        "endpoints": ["/api/v1/sectors/daily"],
    },
    {
        "key": "sector-performance",
        "title": "Sector Performance Chart",
        "status": "planned",
        "href": "/admin/sectors/performance",
        "ready": "1d/5d/30d sector returns exist in sector_daily.",
        "blocked_by": "Needs time-series sector endpoint.",
        "endpoints": ["/api/v1/sectors/daily?sector={sector}&limit=252"],
    },
    {
        "key": "universe-caps",
        "title": "Universe Cap Rank",
        "status": "planned",
        "href": "/admin/universe/caps",
        "ready": "market_cap_daily table exists.",
        "blocked_by": "Needs active-universe/cap endpoint.",
        "endpoints": ["/api/v1/universe/active"],
    },
    {
        "key": "universe-churn",
        "title": "Universe Churn Timeline",
        "status": "planned",
        "href": "/admin/universe/churn",
        "ready": "audit_cap_events table exists.",
        "blocked_by": "Needs cap-events endpoint.",
        "endpoints": ["/api/v1/universe/cap-events?since={date}"],
    },
)


def _clean_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not symbol or not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ticker symbol: {raw}",
        )
    return symbol


def _clean_symbols(raw: str) -> list[str]:
    symbols = []
    seen = set()
    for part in raw.split(","):
        symbol = _clean_symbol(part)
        if symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if not symbols:
        raise HTTPException(status_code=422, detail="At least one symbol is required")
    if len(symbols) > 30:
        raise HTTPException(status_code=422, detail="At most 30 symbols are allowed")
    return symbols


def _source(settings: Settings) -> dict[str, str]:
    return {
        "provider": "cloudflare-dataapi",
        "base_url": settings.dataapi_bridge_base_url(),
    }


def _query_params(
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> str:
    params: dict[str, str | int] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if limit is not None:
        params["limit"] = limit
    return urlencode(params)


async def _dataapi_json(settings: Settings, path: str, scopes: list[str]) -> dict[str, Any]:
    bridge = DataApiBridge(settings)
    if not bridge.configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare Data API bridge is not configured",
        )
    try:
        return await bridge.get_json(path, scopes=scopes)
    except httpx.HTTPStatusError as exc:
        detail = f"Cloudflare Data API returned HTTP {exc.response.status_code}"
        log.warning("terminal_data_dataapi_status_error", path=path, status_code=exc.response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        log.warning("terminal_data_dataapi_error", path=path, error=str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloudflare Data API request failed",
        ) from exc


def register_terminal_data_routes(limiter: Limiter | None = None) -> APIRouter:  # noqa: ARG001
    """Attach Terminal Echo JSON endpoints."""
    global _registered
    if _registered:
        return router

    @router.get("/quotes")
    async def terminal_quotes(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        symbols: str = Query(..., min_length=1, max_length=512),
    ) -> dict[str, Any]:
        parsed = _clean_symbols(symbols)
        payload = await _dataapi_json(
            settings,
            f"/api/v1/market-data/quotes?{urlencode({'symbols': ','.join(parsed)})}",
            scopes=["market:read"],
        )
        log.info("terminal_quotes_read", sub=user["sub"], symbols=parsed)
        return {**payload, "symbols": parsed, "source": _source(settings)}

    @router.get("/tickers/{ticker}/price-history")
    async def terminal_price_history(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        ticker: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=252, ge=1, le=2000),
    ) -> dict[str, Any]:
        symbol = _clean_symbol(ticker)
        params: dict[str, str | int] = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        payload = await _dataapi_json(
            settings,
            f"/api/v1/tickers/{quote(symbol, safe='')}/price-history?{urlencode(params)}",
            scopes=["market:read"],
        )
        log.info("terminal_price_history_read", sub=user["sub"], symbol=symbol, limit=limit)
        return {**payload, "source": _source(settings)}

    @router.get("/analytics/snapshots/{ticker}")
    async def terminal_snapshot(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        ticker: str,
    ) -> dict[str, Any]:
        symbol = _clean_symbol(ticker)
        payload = await _dataapi_json(
            settings,
            f"/api/v1/analytics/snapshots/{quote(symbol, safe='')}",
            scopes=["analytics:read"],
        )
        log.info("terminal_snapshot_read", sub=user["sub"], symbol=symbol)
        return {**payload, "source": _source(settings)}

    @router.get("/indicators/{ticker}/{kind}")
    async def terminal_indicators(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        ticker: str,
        kind: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=252, ge=1, le=2000),
    ) -> dict[str, Any]:
        symbol = _clean_symbol(ticker)
        if kind not in _INDICATOR_KINDS:
            raise HTTPException(status_code=422, detail=f"Unsupported indicator kind: {kind}")
        query_string = _query_params(start=start, end=end, limit=limit)
        payload = await _dataapi_json(
            settings,
            f"/api/v1/indicators/{quote(symbol, safe='')}/{kind}?{query_string}",
            scopes=["analytics:read"],
        )
        log.info("terminal_indicators_read", sub=user["sub"], symbol=symbol, kind=kind, limit=limit)
        return {**payload, "source": _source(settings)}

    @router.get("/news/ticker/{ticker}")
    async def terminal_ticker_news(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        ticker: str,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        symbol = _clean_symbol(ticker)
        payload = await _dataapi_json(
            settings,
            f"/api/v1/news/ticker/{quote(symbol, safe='')}?{urlencode({'limit': limit})}",
            scopes=["market:read"],
        )
        log.info("terminal_ticker_news_read", sub=user["sub"], symbol=symbol, limit=limit)
        return {**payload, "source": _source(settings)}

    @router.get("/news/market")
    async def terminal_market_news(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        payload = await _dataapi_json(
            settings,
            f"/api/v1/news/market?{urlencode({'limit': limit})}",
            scopes=["market:read"],
        )
        log.info("terminal_market_news_read", sub=user["sub"], limit=limit)
        return {**payload, "source": _source(settings)}

    @router.get("/symbols/search")
    async def terminal_symbol_search(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
        settings: SettingsDep,
        q: str = Query(..., min_length=1, max_length=64),
        limit: int = Query(default=10, ge=1, le=25),
    ) -> dict[str, Any]:
        payload = await _dataapi_json(
            settings,
            f"/api/v1/symbols/search?{urlencode({'q': q.strip(), 'limit': limit})}",
            scopes=["symbols:read"],
        )
        log.info("terminal_symbol_search_read", sub=user["sub"], query=q[:32], limit=limit)
        return {**payload, "source": _source(settings)}

    @router.get("/modules")
    async def terminal_modules(
        request: Request,  # noqa: ARG001
        user: CurrentUser,
    ) -> dict[str, Any]:
        roles = normalize_user_roles(user)
        groups: dict[str, list[dict[str, object]]] = {}
        order: list[str] = []
        for module in TERMINAL_MODULES:
            if not user_has_role(roles, module.role_required):
                continue
            if module.nav_group not in groups:
                groups[module.nav_group] = []
                order.append(module.nav_group)
            groups[module.nav_group].append(
                {
                    "key": module.key,
                    "label": module.title,
                    "href": module.href,
                    "implemented": module.implemented,
                    "status": "shipped" if module.implemented else "planned",
                    "notes": module.notes or "",
                    "role_required": module.role_required,
                }
            )
        return {
            "groups": [{"name": name, "modules": groups[name]} for name in order],
            "market_surfaces": list(MARKET_SURFACES),
        }

    _registered = True
    return router
