"""Pre-submission risk + compliance checks for the OMS approve path."""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()


async def check_risk(
    base_url: str,
    *,
    portfolio_id: str,
    instrument_id: int,
    side: str,
    qty: float,
    limit_price: float,
) -> dict[str, object]:
    """Call risk-service ``POST /v1/validate-order``."""
    if not base_url:
        log.debug("risk_gate_skipped", reason="risk_service_http_url unset")
        return {"approved": True, "outcome": "ALLOW", "reason": None}
    payload = {
        "portfolio_id": portfolio_id,
        "instrument_id": instrument_id,
        "side": side,
        "qty": qty,
        "limit_price": limit_price,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{base_url.rstrip('/')}/v1/validate-order", json=payload)
        response.raise_for_status()
        return dict(response.json())


async def check_compliance(
    base_url: str,
    *,
    portfolio_id: str,
    instrument_id: int,
    side: str,
    qty: float,
    limit_price: float,
) -> dict[str, object]:
    """Call compliance-service ``POST /v1/check-order``."""
    if not base_url:
        log.debug("compliance_gate_skipped", reason="compliance_service_http_url unset")
        return {"approved": True, "outcome": "PASS", "reason": None}
    payload = {
        "portfolio_id": portfolio_id,
        "instrument_id": instrument_id,
        "side": side,
        "qty": qty,
        "limit_price": limit_price,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{base_url.rstrip('/')}/v1/check-order", json=payload)
        response.raise_for_status()
        return dict(response.json())
