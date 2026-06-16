"""Redis-backed refresh token rotation, session tracking, and revocation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis

log = structlog.get_logger()

REFRESH_REDIS_PREFIX = "admin:refresh:"
USER_SESSIONS_PREFIX = "admin:user_sessions:"
SESSION_META_PREFIX = "admin:session_meta:"


def refresh_key(jti: str) -> str:
    """Redis key for one refresh token jti."""
    return f"{REFRESH_REDIS_PREFIX}{jti}"


def user_sessions_key(subject: str) -> str:
    """Redis set key listing active refresh jtis for a user."""
    return f"{USER_SESSIONS_PREFIX}{subject}"


def session_meta_key(jti: str) -> str:
    """Redis key for session metadata."""
    return f"{SESSION_META_PREFIX}{jti}"


async def store_refresh_session(
    redis: Redis,
    *,
    jti: str,
    subject: str,
    ttl_seconds: int,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Persist refresh jti, user session index, and metadata."""
    now = datetime.now(tz=UTC).isoformat()
    meta = json.dumps(
        {
            "subject": subject,
            "issued_at": now,
            "last_used_at": now,
            "ip": ip,
            "user_agent": user_agent,
        },
    )
    pipe = redis.pipeline()
    pipe.set(refresh_key(jti), subject, ex=ttl_seconds)
    pipe.sadd(user_sessions_key(subject), jti)
    pipe.set(session_meta_key(jti), meta, ex=ttl_seconds)
    await pipe.execute()


async def consume_refresh_token(redis: Redis, jti: str) -> str | None:
    """Atomically read and delete a refresh token; return subject or None."""
    return await redis.getdel(refresh_key(jti))


async def touch_session_meta(redis: Redis, jti: str, ttl_seconds: int) -> None:
    """Update last_used_at on an active session."""
    raw = await redis.get(session_meta_key(jti))
    if raw is None:
        return
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return
    meta["last_used_at"] = datetime.now(tz=UTC).isoformat()
    await redis.set(session_meta_key(jti), json.dumps(meta), ex=ttl_seconds)


async def revoke_refresh(redis: Redis, jti: str, subject: str | None = None) -> None:
    """Revoke one refresh token and its metadata."""
    if subject is None:
        subject = await redis.get(refresh_key(jti))
    pipe = redis.pipeline()
    pipe.delete(refresh_key(jti))
    pipe.delete(session_meta_key(jti))
    if subject:
        pipe.srem(user_sessions_key(subject), jti)
    await pipe.execute()


async def revoke_all_sessions(redis: Redis, subject: str) -> int:
    """Revoke every refresh token for ``subject``."""
    jtis = await redis.smembers(user_sessions_key(subject))
    if not jtis:
        return 0
    pipe = redis.pipeline()
    for jti in jtis:
        pipe.delete(refresh_key(jti))
        pipe.delete(session_meta_key(jti))
    pipe.delete(user_sessions_key(subject))
    await pipe.execute()
    log.warning("admin_sessions_revoked_all", sub=subject, count=len(jtis))
    return len(jtis)


async def list_sessions(redis: Redis, subject: str) -> list[dict[str, Any]]:
    """Return active session metadata for ``subject``."""
    jtis = await redis.smembers(user_sessions_key(subject))
    sessions: list[dict[str, Any]] = []
    for jti in sorted(jtis):
        raw = await redis.get(session_meta_key(jti))
        if raw is None:
            continue
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            meta = {}
        sessions.append(
            {
                "session_id": jti,
                "issued_at": meta.get("issued_at"),
                "last_used_at": meta.get("last_used_at"),
                "ip": meta.get("ip"),
                "user_agent": meta.get("user_agent"),
            },
        )
    return sessions
