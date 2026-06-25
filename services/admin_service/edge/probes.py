"""Local health and port probes for edge routes."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


async def is_port_listening(host: str, port: int, *, timeout: float = 1.0) -> bool:
    """Return True when a TCP connection to host:port succeeds."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError, ConnectionRefusedError):
        return False


async def probe_http_health(
    host: str,
    port: int,
    path: str,
    *,
    timeout: float = 5.0,
) -> tuple[str, dict[str, Any] | None]:
    """GET health endpoint; return (status_label, json_body_or_none)."""
    url = f"http://{host}:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            body: dict[str, Any] | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        body = parsed
                except ValueError:
                    body = None
            if response.status_code == 200:
                if body and body.get("status") in {"healthy", "ok"}:
                    return "healthy", body
                if body is None and response.status_code == 200:
                    return "healthy", body
                return "unhealthy", body
            return "unhealthy", body
    except (httpx.HTTPError, OSError):
        return "unknown", None
