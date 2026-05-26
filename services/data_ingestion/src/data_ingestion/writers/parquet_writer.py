"""MinIO Parquet snapshot writer."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
from dataclasses import dataclass
from datetime import date

import polars as pl
import structlog
from minio import Minio

from data_ingestion.observability import observe_duration, span

log = structlog.get_logger()

DEFAULT_BUCKET = "theeyebeta-snapshots"
DEFAULT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SnapshotWriteResult:
    """Result of persisting one market/day Parquet object."""

    market: str
    trade_date: date
    blob_uri: str
    sha256_hex: str
    row_count: int


class ParquetWriter:
    """Writes zstd-compressed Parquet snapshots to MinIO."""

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
        return f"{market}/{trade_date.year:04d}/{trade_date.month:02d}/{trade_date.isoformat()}.parquet"

    def _blob_uri(self, market: str, trade_date: date) -> str:
        return f"s3://{self._bucket}/{self._object_key(market, trade_date)}"

    def _write_sync(self, market: str, trade_date: date, frame: pl.DataFrame) -> SnapshotWriteResult:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
        buffer = io.BytesIO()
        frame.write_parquet(buffer, compression="zstd")
        payload = buffer.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        key = self._object_key(market, trade_date)
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(payload),
            length=len(payload),
            content_type="application/vnd.apache.parquet",
        )
        blob_uri = self._blob_uri(market, trade_date)
        log.info(
            "parquet_snapshot_written",
            market=market,
            trade_date=str(trade_date),
            blob_uri=blob_uri,
            row_count=frame.height,
            sha256=digest,
        )
        return SnapshotWriteResult(
            market=market,
            trade_date=trade_date,
            blob_uri=blob_uri,
            sha256_hex=digest,
            row_count=frame.height,
        )

    async def write_daily_snapshot(
        self,
        market: str,
        trade_date: date,
        frame: pl.DataFrame,
    ) -> SnapshotWriteResult:
        """Serialize a Polars frame to zstd Parquet in MinIO."""
        async with observe_duration("parquet", market), span(
            "writer.write_daily_snapshot",
            market=market,
            trade_date=str(trade_date),
        ):
            return await asyncio.to_thread(self._write_sync, market, trade_date, frame)
