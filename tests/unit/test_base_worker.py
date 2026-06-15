"""Unit tests for BaseWorker audit registration semantics."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import asyncpg
import pytest

from workers.base_worker import BaseWorker


def _worker() -> BaseWorker:
    return BaseWorker(database_url="postgresql://unused/unused")


async def test_start_run_returns_run_id() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"run_id": 7})

    run_id = await _worker()._start_run(conn, date(2026, 6, 12), "scheduled", None)

    assert run_id == 7
    assert conn.fetchrow.await_count == 1


async def test_scheduled_duplicate_falls_back_to_recovery() -> None:
    """A second scheduled run for the same (worker, date) must not crash.

    The partial unique index allows one scheduled row per worker/day; the
    rerun is re-registered as recovery so the systemd unit keeps going.
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[asyncpg.UniqueViolationError("duplicate"), {"run_id": 11}],
    )

    run_id = await _worker()._start_run(conn, date(2026, 6, 12), "scheduled", None)

    assert run_id == 11
    assert conn.fetchrow.await_count == 2
    retry_args = conn.fetchrow.await_args_list[1].args
    assert retry_args[4] == "recovery"  # run_type positional parameter


async def test_manual_duplicate_is_not_swallowed() -> None:
    """Only scheduled registrations get the recovery fallback."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate"))

    with pytest.raises(asyncpg.UniqueViolationError):
        await _worker()._start_run(conn, date(2026, 6, 12), "manual", None)
