"""MinIO / S3 uploads for backtest artifacts."""

from __future__ import annotations

from pathlib import Path

import structlog
from minio import Minio

from backtest_engine.settings import Settings

log = structlog.get_logger()


def upload_file(settings: Settings, *, local_path: Path, object_key: str) -> str:
    """Upload a local file to the backtests bucket.

    Returns:
        ``s3://{bucket}/{object_key}`` URI.
    """
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_endpoint.startswith("https"),
    )
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.fput_object(bucket, object_key, str(local_path))
    uri = f"s3://{bucket}/{object_key}"
    log.info("backtest_artifact_uploaded", uri=uri)
    return uri
