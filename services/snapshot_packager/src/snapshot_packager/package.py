"""Shared packaging logic for NATS consumer and HTTP backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import asyncpg
import structlog
from zinc_schemas.packaged_snapshot import PackagedSnapshotV1
from zinc_schemas.snapshot_validator import validate_snapshot

from snapshot_packager.builder import SnapshotBuilder
from snapshot_packager.writers import PackagedSnapshotWriter

log = structlog.get_logger()


@dataclass(frozen=True)
class PackageResult:
    """Outcome of packaging one market/day snapshot."""

    market: str
    trade_date: date
    snapshot_id: UUID
    blob_uri: str
    sha256_hex: str
    universe_size: int


async def package_snapshot(
    pool: asyncpg.Pool,
    market: str,
    trade_date: date,
    *,
    writer: PackagedSnapshotWriter | None = None,
    validate: bool = True,
) -> PackageResult:
    """Build, validate, upload, and catalog one packaged snapshot.

    Args:
        pool: asyncpg pool for Postgres reads/writes.
        market: Aggregated market code (US, HK, JP, TW, CN).
        trade_date: Trading calendar date.
        writer: Optional MinIO writer (default: env-configured).
        validate: When True, run JSON Schema validation before upload.

    Returns:
        Metadata for the persisted snapshot.
    """
    market_upper = market.upper()
    builder = SnapshotBuilder(pool)
    raw = await builder.build(market_upper, trade_date)
    if validate:
        validate_snapshot(raw)
    snapshot = PackagedSnapshotV1.model_validate(raw)
    sink = writer or PackagedSnapshotWriter()
    write_result = await sink.write_minio(snapshot)
    async with pool.acquire() as conn, conn.transaction():
        await sink.record_packaged(
            conn,
            snapshot=snapshot,
            result=write_result,
            trade_date=trade_date,
        )
    log.info(
        "snapshot_packaged",
        market=market_upper,
        trade_date=str(trade_date),
        snapshot_id=str(snapshot.snapshot_id),
        blob_uri=write_result.blob_uri,
    )
    return PackageResult(
        market=market_upper,
        trade_date=trade_date,
        snapshot_id=snapshot.snapshot_id,
        blob_uri=write_result.blob_uri,
        sha256_hex=write_result.sha256_hex,
        universe_size=len(snapshot.universe),
    )
