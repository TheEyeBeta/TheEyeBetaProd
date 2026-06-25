"""HTTP clients for data-ingestion, snapshot-packager, and Data API."""

from __future__ import annotations

import httpx
import structlog
from edge.probes import probe_http_health
from settings import Settings

log = structlog.get_logger()


async def data_ingestion_health(settings: Settings) -> dict[str, object]:
    url = f"{settings.data_ingestion_base_url()}/health"
    async with httpx.AsyncClient(timeout=1.5) as client:
        response = await client.get(url)
        response.raise_for_status()
        return dict(response.json())


async def data_ingestion_metrics_state(settings: Settings) -> dict[str, object]:
    url = f"{settings.data_ingestion_base_url()}/metrics/state"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return dict(response.json())


async def trigger_backfill(
    settings: Settings,
    *,
    adapter: str | None,
    trading_date: str | None,
) -> dict[str, object]:
    url = f"{settings.data_ingestion_base_url()}/ingest/run"
    payload: dict[str, object] = {}
    if adapter:
        payload["adapter"] = adapter
    if trading_date:
        payload["date"] = trading_date
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload or None)
        if response.status_code in {401, 403, 503}:
            return {"status": "auth_required", "detail": response.text[:200]}
        response.raise_for_status()
        return dict(response.json())


async def snapshot_packager_health(settings: Settings) -> dict[str, object]:
    url = f"{settings.snapshot_packager_base_url()}/health"
    async with httpx.AsyncClient(timeout=1.5) as client:
        response = await client.get(url)
        response.raise_for_status()
        return dict(response.json())


async def build_snapshot(
    settings: Settings,
    *,
    market: str,
    trading_date: str,
) -> dict[str, object]:
    url = f"{settings.snapshot_packager_base_url()}/snapshots/build"
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json={"market": market, "date": trading_date})
        response.raise_for_status()
        return dict(response.json())


async def data_api_internal_health(settings: Settings) -> tuple[str, dict[str, object] | None]:
    label, body = await probe_http_health("127.0.0.1", 7000, "/health", timeout=1.0)
    return label, body


async def data_api_public_route_health(
    hostname: str,
    *,
    port: int = 7000,
) -> dict[str, object]:
    label, body = await probe_http_health("127.0.0.1", port, "/health", timeout=1.0)
    return {
        "hostname": hostname,
        "port": port,
        "health": label,
        "reachable": label == "healthy",
        "body": body or {},
    }
