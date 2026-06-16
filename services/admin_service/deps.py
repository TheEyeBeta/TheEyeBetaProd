"""Shared FastAPI dependencies — DB pool, NATS, Redis."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
import nats
import structlog
from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis
from settings import Settings, get_settings

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None
_nats: nats.NATS | None = None
_redis: Redis | None = None
_redis_ops: Redis | None = None


async def init_resources(settings: Settings) -> None:
    """Open connection pools and clients (application lifespan)."""
    global _pool, _nats, _redis, _redis_ops

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10,
        command_timeout=60,
    )
    log.info("admin_db_pool_ready")

    _nats = await nats.connect(settings.nats_url)
    log.info("admin_nats_connected", servers=settings.nats_url)

    _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()
    log.info("admin_redis_connected", db=settings.redis_url)

    _redis_ops = Redis.from_url(settings.redis_ops_url, decode_responses=True)
    await _redis_ops.ping()
    log.info("admin_redis_ops_connected", db=settings.redis_ops_url)


async def close_resources() -> None:
    """Release pools and clients."""
    global _pool, _nats, _redis, _redis_ops

    if _pool is not None:
        await _pool.close()
        _pool = None
    if _nats is not None:
        await _nats.drain()
        await _nats.close()
        _nats = None
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _redis_ops is not None:
        await _redis_ops.aclose()
        _redis_ops = None
    log.info("admin_resources_closed")


async def get_db(
    request: Request,
) -> AsyncIterator[asyncpg.Connection]:
    """Yield one connection from the asyncpg pool."""
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        yield conn


async def get_nats(request: Request) -> nats.NATS:
    """Return the singleton NATS client."""
    client: nats.NATS | None = request.app.state.nats
    if client is None:
        msg = "NATS client is not initialized"
        raise RuntimeError(msg)
    return client


async def get_redis(request: Request) -> Redis:
    """Return the Redis client used for refresh-token rotation."""
    client: Redis | None = request.app.state.redis
    if client is None:
        msg = "Redis client is not initialized"
        raise RuntimeError(msg)
    return client


async def get_redis_ops(request: Request) -> Redis:
    """Return the Redis client for cross-service operational keys (DB 0)."""
    client: Redis | None = request.app.state.redis_ops
    if client is None:
        msg = "Redis ops client is not initialized"
        raise RuntimeError(msg)
    return client


def settings_dep(request: Request) -> Settings:
    """Return the :class:`Settings` bound to ``app.state`` by the lifespan.

    Falls back to the cached module-level singleton when ``app.state.settings``
    is unset (e.g. when an ``APIRouter`` is mounted on a fresh ``FastAPI``
    instance in a test without going through ``create_app``).
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is not None:
        return settings
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]

DbConn = Annotated[asyncpg.Connection, Depends(get_db)]
NatsClient = Annotated[nats.NATS, Depends(get_nats)]
RedisDep = Annotated[Redis, Depends(get_redis)]
RedisOpsDep = Annotated[Redis, Depends(get_redis_ops)]


def bind_app_state(app: FastAPI, settings: Settings) -> None:
    """Attach shared clients to ``app.state`` after ``init_resources``."""
    app.state.settings = settings
    app.state.db_pool = _pool
    app.state.nats = _nats
    app.state.redis = _redis
    app.state.redis_ops = _redis_ops
