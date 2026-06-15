"""Load packaged snapshots from Postgres + MinIO with Redis cache."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

import psycopg
import structlog
from minio import Minio
from redis.asyncio import Redis

from zinc_schemas.snapshot_validator import validate_snapshot

log = structlog.get_logger()

_CACHE_TTL_SECONDS = 3600


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set for SnapshotLoader"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


def _parse_s3_uri(blob_uri: str) -> tuple[str, str]:
    """Return ``(bucket, object_key)`` from an ``s3://`` URI."""
    if not blob_uri.startswith("s3://"):
        msg = f"Unsupported blob_uri scheme (expected s3://): {blob_uri}"
        raise ValueError(msg)
    remainder = blob_uri.removeprefix("s3://")
    bucket, _, key = remainder.partition("/")
    if not bucket or not key:
        msg = f"Invalid s3 URI: {blob_uri}"
        raise ValueError(msg)
    return bucket, key


class SnapshotLoader:
    """Fetch and validate packaged snapshots by ``snapshot_id``."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        redis_url: str | None = None,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        """Configure Postgres and Redis clients; MinIO is initialised on first use."""
        self._database_url = (
            (database_url or _db_url())
            .replace("+asyncpg", "")
            .replace(
                "+psycopg",
                "",
            )
        )
        self._redis_url = redis_url or _redis_url()
        self._cache_ttl = cache_ttl_seconds
        self._redis: Redis | None = None
        self._minio: Minio | None = None

    def _minio_client(self) -> Minio:
        if self._minio is None:
            raw_endpoint = os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")
            host = raw_endpoint.replace("http://", "").replace("https://", "")
            secure = raw_endpoint.startswith("https://")
            self._minio = Minio(
                host,
                access_key=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
                secret_key=os.environ.get("MINIO_ROOT_PASSWORD", ""),
                secure=secure,
            )
        return self._minio

    async def _redis_client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def aclose(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _fetch_blob_sync(self, blob_uri: str) -> bytes:
        bucket, key = _parse_s3_uri(blob_uri)
        response = self._minio_client().get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def load(self, snapshot_id: UUID) -> dict[str, Any]:
        """Load a packaged snapshot dict, using Redis cache when available.

        Args:
            snapshot_id: Packaged snapshot UUID (``data_snapshots_packaged.snapshot_id``).

        Returns:
            Validated snapshot dictionary (schema v1).

        Raises:
            ValueError: When the snapshot row or blob is missing.
        """
        cache_key = f"snapshot:packaged:{snapshot_id}"
        redis = await self._redis_client()
        cached = await redis.get(cache_key)
        if cached:
            log.debug("snapshot_cache_hit", snapshot_id=str(snapshot_id))
            return json.loads(cached)

        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            cur = await conn.execute(
                """
                SELECT blob_uri, market, trade_date
                  FROM theeyebeta.data_snapshots_packaged
                 WHERE snapshot_id = %s
                 ORDER BY packaged_at DESC
                 LIMIT 1
                """,
                (snapshot_id,),
            )
            row = await cur.fetchone()

        if not row:
            msg = f"No packaged snapshot for snapshot_id={snapshot_id}"
            raise ValueError(msg)

        blob_uri, market, trade_date = row
        payload = await asyncio.to_thread(self._fetch_blob_sync, blob_uri)
        raw = json.loads(payload)
        validated = validate_snapshot(raw)
        await redis.setex(cache_key, self._cache_ttl, json.dumps(validated))
        log.info(
            "snapshot_loaded",
            snapshot_id=str(snapshot_id),
            market=market,
            trade_date=str(trade_date),
            blob_uri=blob_uri,
        )
        return validated
