"""Persist packaged snapshots to MinIO and Postgres."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import asyncpg
import structlog
from minio import Minio

from zinc_schemas.packaged_snapshot import PACKAGED_SCHEMA_VERSION, PackagedSnapshotV1

log = structlog.get_logger()

DEFAULT_BUCKET = "theeyebeta-snapshots"


@dataclass(frozen=True)
class PackagedWriteResult:
    """Result of uploading one packaged JSON snapshot."""

    blob_uri: str
    sha256_hex: str
    object_key: str
    snapshot_id: UUID


class PackagedSnapshotWriter:
    """Write agent-ready JSON snapshots to MinIO and catalog rows in Postgres."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        raw_endpoint = endpoint or os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")
        host = raw_endpoint.replace("http://", "").replace("https://", "")
        use_ssl = secure if secure is not None else raw_endpoint.startswith("https://")
        self._client = Minio(
            host,
            access_key=access_key or os.environ.get("MINIO_ROOT_USER", "minioadmin"),
            secret_key=secret_key or os.environ.get("MINIO_ROOT_PASSWORD", ""),
            secure=use_ssl,
        )
        self._bucket = bucket or os.environ.get("MINIO_SNAPSHOT_BUCKET", DEFAULT_BUCKET)

    def _object_key(self, market: str, trade_date: date) -> str:
        return (
            f"packaged/{market}/{trade_date.year:04d}/"
            f"{trade_date.month:02d}/{trade_date.isoformat()}.json"
        )

    @staticmethod
    def object_key_for(market: str, trade_date: date) -> str:
        """Return the MinIO object key for a packaged snapshot."""
        return (
            f"packaged/{market}/{trade_date.year:04d}/"
            f"{trade_date.month:02d}/{trade_date.isoformat()}.json"
        )

    def _write_sync(self, snapshot: PackagedSnapshotV1) -> PackagedWriteResult:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
        payload = json.dumps(snapshot.model_dump(mode="json"), separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()
        key = self._object_key(snapshot.market, snapshot.as_of.date())
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )
        blob_uri = f"s3://{self._bucket}/{key}"
        log.info(
            "packaged_snapshot_uploaded",
            market=snapshot.market,
            trade_date=str(snapshot.as_of.date()),
            blob_uri=blob_uri,
            bytes=len(payload),
        )
        return PackagedWriteResult(
            blob_uri=blob_uri,
            sha256_hex=digest,
            object_key=key,
            snapshot_id=snapshot.snapshot_id,
        )

    async def write_minio(self, snapshot: PackagedSnapshotV1) -> PackagedWriteResult:
        """Upload snapshot JSON to MinIO (blocking I/O offloaded to a thread)."""
        return await asyncio.to_thread(self._write_sync, snapshot)

    def _read_sync(self, market: str, trade_date: date) -> bytes:
        key = self.object_key_for(market, trade_date)
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def read_bytes(self, market: str, trade_date: date) -> bytes:
        """Fetch packaged snapshot JSON bytes from MinIO."""
        return await asyncio.to_thread(self._read_sync, market, trade_date)

    async def record_packaged(
        self,
        conn: asyncpg.Connection,
        *,
        snapshot: PackagedSnapshotV1,
        result: PackagedWriteResult,
        trade_date: date,
    ) -> UUID:
        """Insert a ``data_snapshots_packaged`` catalog row."""
        row = await conn.fetchrow(
            """
            INSERT INTO theeyebeta.data_snapshots_packaged
                (snapshot_id, market, trade_date, schema_version, blob_uri,
                 blob_sha256, universe_size, packager_git_sha)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (market, trade_date, schema_version) DO UPDATE
                SET snapshot_id     = EXCLUDED.snapshot_id,
                    blob_uri        = EXCLUDED.blob_uri,
                    blob_sha256     = EXCLUDED.blob_sha256,
                    universe_size   = EXCLUDED.universe_size,
                    packaged_at     = now(),
                    packager_git_sha = EXCLUDED.packager_git_sha
            RETURNING id
            """,
            snapshot.snapshot_id,
            snapshot.market,
            trade_date,
            PACKAGED_SCHEMA_VERSION,
            result.blob_uri,
            bytes.fromhex(result.sha256_hex),
            len(snapshot.universe),
            os.environ.get("GIT_COMMIT", "dev"),
        )
        return row["id"]
