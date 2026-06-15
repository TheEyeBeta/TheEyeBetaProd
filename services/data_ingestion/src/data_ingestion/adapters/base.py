"""Adapter protocol, HTTP client factory, and instrument helpers."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog

from zinc_schemas.ingestion import Record

log = structlog.get_logger()

HTTP_TIMEOUT_SECONDS = 30.0
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

_YFINANCE_EXCHANGES = frozenset({"XNAS", "XNYS", "XTKS", "XHKG", "XTAI"})
_CN_EXCHANGES = frozenset({"XSHG", "XSHE"})
_US_EXCHANGES = frozenset({"XNAS", "XNYS"})


def make_http_client() -> httpx.AsyncClient:
    """Return an async HTTP client with a 30s timeout."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)


def ingest_dsn() -> str:
    """Resolve a PostgreSQL DSN from INGEST_DATABASE_URL."""
    raw = os.environ.get("INGEST_DATABASE_URL", "")
    if not raw:
        raise OSError("INGEST_DATABASE_URL is not set")
    return re.sub(r"\+\w+", "", raw, count=1)


async def load_active_instruments(
    dsn: str | None = None,  # noqa: ARG001 — pool uses env DSN
    *,
    exchange_codes: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Load active instruments via the shared asyncpg pool."""
    from data_ingestion.writers.postgres_writer import get_pool  # noqa: PLC0415

    pool = await get_pool()
    async with pool.acquire() as conn:
        if exchange_codes:
            rows = await conn.fetch(
                """
                SELECT i.id, i.symbol, e.code AS exchange_code
                FROM theeyebeta.instruments i
                JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                WHERE i.active = true AND e.code = ANY($1::text[])
                ORDER BY i.symbol
                """,
                list(exchange_codes),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT i.id, i.symbol, e.code AS exchange_code
                FROM theeyebeta.instruments i
                JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                WHERE i.active = true
                ORDER BY i.symbol
                """
            )

    return [
        {"instrument_id": r["id"], "symbol": r["symbol"], "exchange_code": r["exchange_code"]}
        for r in rows
    ]


class DataAdapter(Protocol):
    """Pluggable ingestion adapter."""

    name: str

    async def fetch(self, target_date: date) -> AsyncIterator[Record]:
        """Yield normalized records for the given calendar date."""
        ...
