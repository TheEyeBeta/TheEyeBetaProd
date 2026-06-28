"""MASTER_ADMIN DataAPI bridge.

The browser must never receive DataAPI service credentials. This bridge lets a
validated admin-service JWT access DataAPI read surfaces through a server-side
service client.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any
from urllib.parse import unquote

import asyncpg
import httpx
import structlog
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from rbac import Role, require_role
from settings import Settings

log = structlog.get_logger()

router = APIRouter(prefix="/dataapi", tags=["dataapi"])

_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}
_TOKEN_SKEW_SECONDS = 60.0
_TOKEN_TIMEOUT_SECONDS = 20.0
_PROXY_TIMEOUT_SECONDS = 60.0
_PRICE_HISTORY_DEFAULT_START = date(2021, 1, 1)
_PRICE_HISTORY_DEFAULT_LIMIT = 252
_PRICE_HISTORY_MAX_LIMIT = 2000
_SCALE_REPAIR_FACTORS = (10.0, 20.0)
_SCALE_REPAIR_TOLERANCE = 0.20
_SCALE_REPAIR_MAX_DAYS = 370

PRICE_HISTORY_SQL = """
WITH inst AS (
    SELECT id, symbol
      FROM theeyebeta.instruments
     WHERE UPPER(symbol) = UPPER($1)
     LIMIT 1
),
ranked_prices AS (
    SELECT p.ts::date AS d,
           p.open,
           p.high,
           p.low,
           p.close,
           p.adj_close,
           p.volume,
           p.vwap,
           ROW_NUMBER() OVER (
               PARTITION BY p.ts::date
               ORDER BY
                   CASE p.source
                       WHEN 'massive' THEN 100
                       WHEN 'yfinance_backfill_prices' THEN 90
                       WHEN 'yfinance_gap_fix' THEN 90
                       WHEN 'yfinance' THEN 80
                       WHEN 'finnhub' THEN 70
                       WHEN 'public_mirror_backfill' THEN 60
                       WHEN 'public_mirror_active_universe' THEN 50
                       WHEN 'tick_rollup' THEN 40
                       WHEN 'csv' THEN 10
                       ELSE 0
                   END DESC,
                   p.ts DESC,
                   p.ingested_at DESC
           ) AS rn
      FROM theeyebeta.prices_daily p
      JOIN inst i ON i.id = p.instrument_id
     WHERE p.ts::date <= $2
       AND p.close > 0
)
SELECT d, open, high, low, close, adj_close, volume, vwap
  FROM ranked_prices
 WHERE rn = 1
 ORDER BY d
"""


def _configured(settings: Settings) -> bool:
    return bool(settings.dataapi_client_id.strip() and settings.dataapi_client_secret.strip())


async def _issue_dataapi_token(settings: Settings) -> str:
    """Fetch and cache a scoped DataAPI service JWT."""
    if not _configured(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dataapi_bridge_not_configured",
                    "message": "ADMIN_DATAAPI_CLIENT_ID/SECRET are not configured",
                    "details": {},
                },
            },
        )

    now = time.monotonic()
    cached_token = str(_TOKEN_CACHE.get("token") or "")
    cached_expires_at = float(_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached_token and cached_expires_at > now + _TOKEN_SKEW_SECONDS:
        return cached_token

    token_url = f"{settings.dataapi_url.rstrip('/')}/api/v1/auth/service-token"
    try:
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                token_url,
                auth=(settings.dataapi_client_id, settings.dataapi_client_secret),
                json={"requested_scopes": settings.dataapi_scope_list()},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dataapi_unreachable",
                    "message": "DataAPI service-token endpoint is unreachable",
                    "details": {},
                },
            },
        ) from exc

    if response.status_code >= 400:
        log.warning(
            "admin_dataapi_token_failed",
            status_code=response.status_code,
            body=response.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "code": "dataapi_token_failed",
                    "message": "DataAPI rejected admin bridge service credentials",
                    "details": {"status_code": response.status_code},
                },
            },
        )

    payload = response.json()
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "code": "dataapi_token_missing",
                    "message": "DataAPI service-token response did not include an access token",
                    "details": {},
                },
            },
        )
    expires_minutes = float(payload.get("expires_minutes") or 5)
    _TOKEN_CACHE["token"] = access_token
    _TOKEN_CACHE["expires_at"] = now + max(60.0, expires_minutes * 60.0)
    return access_token


def _validate_proxy_path(path: str) -> str:
    cleaned = path.strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "invalid_dataapi_path",
                    "message": "Invalid DataAPI proxy path",
                    "details": {},
                },
            },
        )
    normalized = "/".join(parts)
    if normalized.startswith("api/v1/auth/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "dataapi_auth_proxy_forbidden",
                    "message": "DataAPI auth endpoints are not exposed through the admin bridge",
                    "details": {},
                },
            },
        )
    return f"/{normalized}"


def _proxy_response(response: httpx.Response) -> Response:
    content_type = response.headers.get("content-type", "application/json")
    if "application/json" in content_type.lower():
        try:
            content: Any = response.json()
        except ValueError:
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=content_type,
            )
        return JSONResponse(content=content, status_code=response.status_code)
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type,
    )


def _parse_date_query(value: str | None, *, fallback: date | None = None) -> date | None:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_date", "message": f"Invalid date {value!r}"}},
        ) from exc


def _parse_limit_query(value: str | None) -> int:
    if not value:
        return _PRICE_HISTORY_DEFAULT_LIMIT
    try:
        limit = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_limit", "message": f"Invalid limit {value!r}"}},
        ) from exc
    return max(1, min(_PRICE_HISTORY_MAX_LIMIT, limit))


def _price_history_symbol(dataapi_path: str) -> str | None:
    parts = [part for part in dataapi_path.strip("/").split("/") if part]
    if len(parts) == 5 and parts[:3] == ["api", "v1", "tickers"] and parts[4] == "price-history":
        return unquote(parts[3]).upper()
    return None


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


def _scale_row(row: dict[str, object], factor: float) -> None:
    for key in ("open", "high", "low", "close", "adj_close", "vwap"):
        value = row.get(key)
        if value is not None:
            row[key] = float(value) * factor
    volume = row.get("volume")
    if volume is not None:
        row["volume"] = round(float(volume) / factor)


def _nearest_scale_factor(estimated: float) -> float | None:
    for factor in _SCALE_REPAIR_FACTORS:
        if abs(estimated / factor - 1.0) <= _SCALE_REPAIR_TOLERANCE:
            return factor
    return None


def _normalize_bounded_scale_intervals(rows: list[dict[str, object]]) -> None:
    """Fix bounded 10x/20x low-scale spans in the response without mutating DB rows."""
    closes = [_float_or_none(row.get("close")) for row in rows]
    jumps: list[dict[str, object]] = []
    for idx in range(1, len(rows)):
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            continue
        ratio = cur / prev
        if ratio < 1.0 / 3.0:
            jumps.append({"idx": idx, "direction": "down", "ratio": ratio})
        elif ratio > 3.0:
            jumps.append({"idx": idx, "direction": "up", "ratio": ratio})

    down_jumps = [jump for jump in jumps if jump["direction"] == "down"]
    up_jumps = [jump for jump in jumps if jump["direction"] == "up"]
    repaired_ranges: list[tuple[int, int]] = []
    for down in down_jumps:
        down_idx = int(down["idx"])
        down_ratio = float(down["ratio"])
        down_date = rows[down_idx]["date"]
        for up in up_jumps:
            up_idx = int(up["idx"])
            if up_idx <= down_idx:
                continue
            up_date = rows[up_idx]["date"]
            if (
                date.fromisoformat(str(up_date)) - date.fromisoformat(str(down_date))
            ).days > _SCALE_REPAIR_MAX_DAYS:
                break
            up_ratio = float(up["ratio"])
            estimated = ((1.0 / down_ratio) + up_ratio) / 2.0
            factor = _nearest_scale_factor(estimated)
            if factor is None:
                continue
            # Avoid double-scaling overlapping intervals.
            if any(not (up_idx - 1 < start or down_idx > end) for start, end in repaired_ranges):
                break
            for row in rows[down_idx:up_idx]:
                _scale_row(row, factor)
            repaired_ranges.append((down_idx, up_idx - 1))
            break


def _price_row(row: asyncpg.Record) -> dict[str, object]:
    return {
        "date": row["d"].isoformat(),
        "open": _float_or_none(row["open"]),
        "high": _float_or_none(row["high"]),
        "low": _float_or_none(row["low"]),
        "close": _float_or_none(row["close"]),
        "adj_close": _float_or_none(row["adj_close"]),
        "volume": _float_or_none(row["volume"]),
        "vwap": _float_or_none(row["vwap"]),
    }


async def _local_price_history_response(
    conn: asyncpg.Connection,
    *,
    ticker: str,
    request: Request,
) -> JSONResponse:
    end_date = _parse_date_query(request.query_params.get("end"), fallback=date.today())
    assert end_date is not None
    start_date = _parse_date_query(request.query_params.get("start"))
    limit = _parse_limit_query(request.query_params.get("limit"))

    rows = await conn.fetch(PRICE_HISTORY_SQL, ticker, end_date)
    prices = [_price_row(row) for row in rows]
    _normalize_bounded_scale_intervals(prices)
    if start_date is not None:
        prices = [row for row in prices if date.fromisoformat(str(row["date"])) >= start_date]
    if len(prices) > limit:
        prices = prices[-limit:]
    return JSONResponse({"ticker": ticker.upper(), "prices": prices})


def register_dataapi_routes() -> APIRouter:
    """Attach MASTER_ADMIN DataAPI read proxy handlers."""

    @router.get("/{path:path}", summary="Proxy DataAPI GET request (MASTER_ADMIN)")
    async def proxy_dataapi_get(
        path: str,
        request: Request,
        settings: SettingsDep,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> Response:
        """Proxy DataAPI GET requests with a server-side scoped service token."""
        dataapi_path = _validate_proxy_path(path)
        local_ticker = _price_history_symbol(dataapi_path)
        if local_ticker is not None:
            log.info("admin_dataapi_local_price_history", sub=user["sub"], ticker=local_ticker)
            return await _local_price_history_response(conn, ticker=local_ticker, request=request)

        token = await _issue_dataapi_token(settings)
        url = f"{settings.dataapi_url.rstrip('/')}{dataapi_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Admin-Actor": user["sub"],
            "X-Request-ID": getattr(request.state, "correlation_id", ""),
        }
        try:
            async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    url,
                    params=request.query_params.multi_items(),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "code": "dataapi_unreachable",
                        "message": "DataAPI request failed",
                        "details": {"path": dataapi_path},
                    },
                },
            ) from exc

        log.info(
            "admin_dataapi_proxy_get",
            sub=user["sub"],
            path=dataapi_path,
            status_code=response.status_code,
        )
        return _proxy_response(response)

    return router
