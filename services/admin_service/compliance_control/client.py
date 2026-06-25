"""HTTP client for compliance-service check bridge."""

from __future__ import annotations

import httpx
import structlog
from settings import Settings

log = structlog.get_logger()


async def check_order(
    settings: Settings,
    *,
    portfolio_id: str,
    instrument_id: int,
    side: str = "buy",
    qty: float = 1.0,
    limit_price: float = 100.0,
    order_id: str | None = None,
) -> dict[str, object]:
    """Call compliance-service ``POST /v1/check-order`` when reachable."""
    url = f"{settings.compliance_http_base_url()}/v1/check-order"
    payload = {
        "portfolio_id": portfolio_id,
        "instrument_id": instrument_id,
        "side": side,
        "qty": qty,
        "limit_price": limit_price,
    }
    if order_id:
        payload["order_id"] = order_id
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
            return dict(body)
    except (httpx.HTTPError, OSError) as exc:
        log.warning("compliance_recheck_remote_failed", error=str(exc))
        raise
