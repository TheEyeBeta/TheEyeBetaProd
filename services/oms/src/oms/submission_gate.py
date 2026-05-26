"""Pause new order submissions when reconciliation drift is detected."""

from __future__ import annotations

import structlog

log = structlog.get_logger()

_REDIS_KEY = "oms:submissions_paused"
_paused_in_memory = False


class SubmissionGate:
    """Gate approve/submit paths while reconciliation drift is unresolved."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url

    async def is_paused(self) -> bool:
        """Return True when new submissions must be blocked."""
        if not self._redis_url:
            return _paused_in_memory
        try:
            import redis.asyncio as aioredis  # noqa: PLC0415

            client = aioredis.from_url(self._redis_url, decode_responses=True)
            try:
                value = await client.get(_REDIS_KEY)
                return value == "1"
            finally:
                await client.aclose()
        except Exception as exc:  # noqa: BLE001
            log.warning("submission_gate_redis_fallback", error=str(exc))
            return _paused_in_memory

    async def pause(self, *, reason: str) -> None:
        """Block new submissions."""
        global _paused_in_memory  # noqa: PLW0603
        _paused_in_memory = True
        if self._redis_url:
            try:
                import redis.asyncio as aioredis  # noqa: PLC0415

                client = aioredis.from_url(self._redis_url, decode_responses=True)
                try:
                    await client.set(_REDIS_KEY, "1")
                finally:
                    await client.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("submission_gate_pause_redis_failed", error=str(exc))
        log.warning("oms_submissions_paused", reason=reason)

    async def resume(self) -> None:
        """Allow new submissions after drift is resolved."""
        global _paused_in_memory  # noqa: PLW0603
        _paused_in_memory = False
        if self._redis_url:
            try:
                import redis.asyncio as aioredis  # noqa: PLC0415

                client = aioredis.from_url(self._redis_url, decode_responses=True)
                try:
                    await client.delete(_REDIS_KEY)
                finally:
                    await client.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("submission_gate_resume_redis_failed", error=str(exc))
        log.info("oms_submissions_resumed")
