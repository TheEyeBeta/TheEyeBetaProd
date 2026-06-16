"""Pause new order submissions when reconciliation drift or emergency halt."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger()

_KEY_TEMPLATE = "oms:submissions_paused:{source}"


class PauseSource(StrEnum):
    """Reason category for submission pause."""

    RECONCILIATION = "reconciliation"
    EMERGENCY = "emergency"


def _redis_key(source: PauseSource) -> str:
    """Return the Redis key for a pause source."""
    return _KEY_TEMPLATE.format(source=source.value)


def _fresh_local_paused() -> dict[PauseSource, bool]:
    """Return a fresh per-instance in-memory pause map."""
    return {
        PauseSource.RECONCILIATION: False,
        PauseSource.EMERGENCY: False,
    }


class SubmissionGate:
    """Gate approve/submit paths while reconciliation drift or emergency halt."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None
        self._paused_local = _fresh_local_paused()

    async def _get_client(self) -> aioredis.Redis | None:
        if not self._redis_url:
            return None
        if self._client is None:
            import redis.asyncio as aioredis_mod  # noqa: PLC0415

            self._client = aioredis_mod.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        """Close the persistent Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def is_source_paused(self, source: PauseSource) -> bool:
        """Return True when the given pause source is active."""
        if not self._redis_url:
            return self._paused_local[source]
        try:
            client = await self._get_client()
            if client is None:
                return self._paused_local[source]
            value = await client.get(_redis_key(source))
            return value == "1"
        except Exception as exc:  # noqa: BLE001
            log.warning("submission_gate_redis_fallback", source=source.value, error=str(exc))
            return self._paused_local[source]

    async def is_paused(self) -> bool:
        """Return True when any pause source blocks new submissions."""
        for source in PauseSource:
            if await self.is_source_paused(source):
                return True
        return False

    async def pause(self, *, source: PauseSource, reason: str) -> None:
        """Block new submissions for the given source."""
        self._paused_local[source] = True
        if self._redis_url:
            try:
                client = await self._get_client()
                if client is not None:
                    await client.set(_redis_key(source), "1")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "submission_gate_pause_redis_failed",
                    source=source.value,
                    error=str(exc),
                )
        log.warning("oms_submissions_paused", source=source.value, reason=reason)

    async def resume(self, *, source: PauseSource) -> None:
        """Clear pause for the given source only."""
        self._paused_local[source] = False
        if self._redis_url:
            try:
                client = await self._get_client()
                if client is not None:
                    await client.delete(_redis_key(source))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "submission_gate_resume_redis_failed",
                    source=source.value,
                    error=str(exc),
                )
        log.info("oms_submissions_resumed", source=source.value)
