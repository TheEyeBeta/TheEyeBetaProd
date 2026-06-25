"""HTTP client for risk-service compute bridge."""

from __future__ import annotations

import httpx
import structlog
from settings import Settings

log = structlog.get_logger()


async def validate_order(
    settings: Settings,
    *,
    portfolio_id: str,
    instrument_id: int,
    side: str = "buy",
    qty: float = 1.0,
    limit_price: float = 100.0,
) -> dict[str, object]:
    """Call risk-service ``POST /v1/validate-order`` when reachable."""
    url = f"{settings.risk_http_base_url()}/v1/validate-order"
    payload = {
        "portfolio_id": portfolio_id,
        "instrument_id": instrument_id,
        "side": side,
        "qty": qty,
        "limit_price": limit_price,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return dict(response.json())


async def compute_portfolio_metrics(settings: Settings, portfolio_id: str) -> dict[str, float | str]:
    """Call risk-service ``POST /v1/compute-portfolio-metrics`` when reachable."""
    url = f"{settings.risk_http_base_url()}/v1/compute-portfolio-metrics"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json={"portfolio_id": portfolio_id})
            response.raise_for_status()
            body = response.json()
            return {k: body[k] for k in body if k != "portfolio_id"} | {"portfolio_id": portfolio_id}
    except (httpx.HTTPError, OSError) as exc:
        log.warning("risk_compute_remote_failed", error=str(exc))
        raise
