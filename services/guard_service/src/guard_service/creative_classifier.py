"""Haiku creative-exploration language classifier (P-GS-02)."""

from __future__ import annotations

import hashlib
import os
import re
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from zinc_schemas.llm_client import LLMClient

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient

log = structlog.get_logger()

CREATIVE_THRESHOLD = 0.6
_CACHE_TTL_SECONDS = 3600
_MODEL = "claude-haiku-4-5"
_PROMPT_CACHE_KEY = "guard-creative-classifier-v1"

SYSTEM_PROMPT = (
    "You score how much a piece of text contains creative-exploration language. "
    "Score 0 for purely factual/structured output. "
    "Score 1 for suggestions, recommendations, alternatives, or improvement proposals. "
    "Examples of high-score patterns: 'I suggest...', 'a better approach...', "
    "'have you considered...'. "
    "Examples of low-score: structured JSON, factual claims about market data, "
    "decisions with evidence_refs. "
    "Output ONLY a number 0-1."
)

_SCORE_RE = re.compile(r"(?<![\d.])(0(?:\.\d+)?|1(?:\.0+)?)(?![\d.])")


def _virtual_key() -> str:
    return os.environ.get("LITELLM_KEY_GUARD_SERVICE_CLASSIFIER", "")


def _base_url() -> str:
    return os.environ.get("LITELLM_PROXY_URL", "http://llm-gateway:4000").rstrip("/")


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


def _cache_key(agent_id: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"guard:creative:{agent_id}:{digest}"


def parse_score(content: str | dict | list | None) -> float:
    """Parse a [0, 1] score from model output."""
    if content is None:
        return 0.0
    if isinstance(content, (int, float)):
        return _clamp(float(content))
    text = str(content).strip()
    if not text:
        return 0.0
    try:
        return _clamp(float(text))
    except ValueError:
        pass
    match = _SCORE_RE.search(text)
    if match:
        return _clamp(float(match.group(1)))
    return 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class CreativeContentClassifier:
    """Scores rationale text for creative-exploration language via Haiku."""

    def __init__(
        self,
        *,
        virtual_key: str | None = None,
        base_url: str | None = None,
        redis_url: str | None = None,
        threshold: float = CREATIVE_THRESHOLD,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        """Configure LiteLLM credentials and optional Redis cache."""
        self._virtual_key = virtual_key if virtual_key is not None else _virtual_key()
        self._base_url = (base_url or _base_url()).rstrip("/")
        self._redis_url = redis_url or _redis_url()
        self._threshold = threshold
        self._cache_ttl = cache_ttl_seconds
        self._redis: RedisClient | None = None

    async def _redis_client(self) -> RedisClient:
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def aclose(self) -> None:
        """Close Redis connection when used."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def classify(self, text: str, *, agent_id: str) -> float:
        """Return creative-exploration probability in [0, 1] for ``text``.

        Args:
            text: Rationale or other executor output fragment to score.
            agent_id: Agent PK used in the Redis cache key.

        Returns:
            Score in [0, 1]. Returns 0.0 when the classifier key is not configured.
        """
        if not text.strip():
            return 0.0
        if not self._virtual_key.startswith("sk-"):
            log.debug("creative_classifier_disabled", reason="missing virtual key")
            return 0.0

        cache_key = _cache_key(agent_id, text)
        redis = await self._redis_client()
        cached = await redis.get(cache_key)
        if cached is not None:
            log.debug("creative_classifier_cache_hit", agent_id=agent_id)
            return _clamp(float(cached))

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[:2000]},
        ]
        score = 0.0
        try:
            async with LLMClient(
                self._virtual_key,
                self._base_url,
                database_url=None,
            ) as llm:
                response = await llm.chat(
                    _MODEL,
                    messages,
                    max_tokens=10,
                    temperature=0.0,
                    prompt_cache_key=_PROMPT_CACHE_KEY,
                )
            score = parse_score(response.content)
        except Exception as exc:  # noqa: BLE001
            log.warning("creative_classifier_failed", agent_id=agent_id, error=str(exc))
            return 0.0

        await redis.setex(cache_key, self._cache_ttl, f"{score:.6f}")
        log.info(
            "creative_classifier_scored",
            agent_id=agent_id,
            score=score,
            flagged=score >= self._threshold,
        )
        return score

    async def score(self, text: str, *, agent_id: str = "") -> float:
        """Alias for :meth:`classify` (validator protocol compatibility)."""
        return await self.classify(text, agent_id=agent_id or "_default")

    def is_flagged(self, score: float) -> bool:
        """Return True when ``score`` meets the creative-content threshold."""
        return score >= self._threshold
