"""Database connection helpers for tb CLI."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import asyncpg
import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    """Return asyncpg/psycopg-compatible DSN from environment."""
    raw = (
        os.environ.get("INGEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MACRO_DATABASE_URL")
        or ""
    )
    if not raw:
        msg = "Set DATABASE_URL or INGEST_DATABASE_URL"
        raise RuntimeError(msg)
    return re.sub(r"\+\w+", "", raw, count=1)


@asynccontextmanager
async def async_connect() -> AsyncIterator[asyncpg.Connection]:
    """Open a single asyncpg connection."""
    conn = await asyncpg.connect(database_url())
    try:
        yield conn
    finally:
        await conn.close()


@contextmanager
def sync_connect() -> Iterator[psycopg.Connection[Any]]:
    """Open a sync psycopg connection with dict rows."""
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn
