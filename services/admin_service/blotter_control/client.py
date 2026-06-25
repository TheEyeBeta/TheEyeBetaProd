"""HTTP clients for broker adapter and OMS."""

from __future__ import annotations

import httpx
import structlog
from settings import Settings

log = structlog.get_logger()


async def broker_health(settings: Settings) -> dict[str, object]:
    url = f"{settings.broker_adapter_url.rstrip('/')}/health"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return dict(response.json())


async def broker_positions(settings: Settings) -> list[dict[str, object]]:
    url = f"{settings.broker_adapter_url.rstrip('/')}/v1/positions"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()
        positions = body.get("positions") or []
        return [dict(item) for item in positions]


async def broker_orders(settings: Settings) -> list[dict[str, object]]:
    url = f"{settings.broker_adapter_url.rstrip('/')}/v1/orders"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()
        orders = body.get("orders") or []
        return [dict(item) for item in orders]


async def oms_health(settings: Settings) -> dict[str, object]:
    url = f"{settings.oms_http_base_url()}/health"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return dict(response.json())


async def oms_resolve_reconciliation(settings: Settings) -> dict[str, object]:
    url = f"{settings.oms_http_base_url()}/oms/reconciliation/resolve"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url)
        response.raise_for_status()
        return dict(response.json())
