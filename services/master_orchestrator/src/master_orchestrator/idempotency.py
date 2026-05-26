"""Redis SETNX idempotency for market-trio workflows."""

from __future__ import annotations

import os
from datetime import date

import structlog
from redis.asyncio import Redis

log = structlog.get_logger()

TTL_SECONDS = 7 * 24 * 3600


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


def trio_key(market: str, trade_date: date) -> str:
    """Redis key for one market/day trio orchestration lock."""
    return f"orchestrator:trio:{market.upper()}:{trade_date.isoformat()}"


class TrioIdempotencyLock:
    """Acquire a 7-day Redis lock before running a market trio."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis
        self._owned = False

    async def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(_redis_url(), decode_responses=True)
            self._owned = True
        return self._redis

    async def try_acquire(self, market: str, trade_date: date) -> bool:
        """Return True when this worker should run the trio (SETNX succeeded)."""
        client = await self._client()
        acquired = await client.set(
            trio_key(market, trade_date),
            "in_progress",
            nx=True,
            ex=TTL_SECONDS,
        )
        if not acquired:
            log.info(
                "market_trio_skipped_duplicate",
                market=market,
                trade_date=str(trade_date),
            )
        return bool(acquired)

    async def mark_complete(self, market: str, trade_date: date, order_id: str) -> None:
        """Store the proposed order id for the idempotency key."""
        client = await self._client()
        await client.set(trio_key(market, trade_date), order_id, ex=TTL_SECONDS)

    async def release(self, market: str, trade_date: date) -> None:
        """Drop the lock so a failed run can be retried."""
        client = await self._client()
        await client.delete(trio_key(market, trade_date))

    async def close(self) -> None:
        """Close a client opened by this helper."""
        if self._owned and self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            self._owned = False
