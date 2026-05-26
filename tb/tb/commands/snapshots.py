"""``tb snapshots`` — backfill and verify packaged snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import date, timedelta
from typing import Any

import asyncpg
import httpx
import structlog
import typer
from dotenv import load_dotenv
from minio import Minio
from zinc_schemas.packaged_snapshot import PACKAGED_SCHEMA_VERSION
from zinc_schemas.snapshot_validator import SnapshotValidationError, validate_snapshot

load_dotenv()
log = structlog.get_logger()

app = typer.Typer(no_args_is_help=True, help="Packaged snapshot backfill and verification")

DEFAULT_PACKAGER_URL = "http://127.0.0.1:7011"


def _packager_url() -> str:
    return os.environ.get("SNAPSHOT_PACKAGER_URL", DEFAULT_PACKAGER_URL).rstrip("/")


def _database_url() -> str:
    raw = os.environ.get("INGEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "INGEST_DATABASE_URL or DATABASE_URL must be set"
        raise typer.BadParameter(msg)
    return re.sub(r"\+\w+", "", raw, count=1)


def _minio_client() -> Minio:
    raw_endpoint = os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")
    host = raw_endpoint.replace("http://", "").replace("https://", "")
    secure = raw_endpoint.startswith("https://")
    return Minio(
        host,
        access_key=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.environ.get("MINIO_ROOT_PASSWORD", ""),
        secure=secure,
    )


def _object_key(market: str, trade_date: date) -> str:
    return (
        f"packaged/{market}/{trade_date.year:04d}/"
        f"{trade_date.month:02d}/{trade_date.isoformat()}.json"
    )


def _fetch_blob_bytes(market: str, trade_date: date) -> bytes:
    bucket = os.environ.get("MINIO_SNAPSHOT_BUCKET", "theeyebeta-snapshots")
    client = _minio_client()
    response = client.get_object(bucket, _object_key(market, trade_date))
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _business_days(start: date, end: date) -> list[date]:
    """Inclusive range of weekdays between start and end."""
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


@app.command("backfill")
def backfill(
    market: str = typer.Option(..., "--market", "-m", help="Market code (US, HK, JP, TW, CN)"),
    start: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD (inclusive)"),
    end: str = typer.Option(..., "--end", help="End date YYYY-MM-DD (inclusive)"),
) -> None:
    """Request packaged snapshots for each weekday in the range via the packager HTTP API."""
    market_upper = market.upper()
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if end_date < start_date:
        raise typer.BadParameter("--end must be on or after --start")

    targets = _business_days(start_date, end_date)
    typer.echo(f"Backfilling {len(targets)} weekdays for {market_upper} via {_packager_url()}")

    ok = 0
    failed = 0
    with httpx.Client(timeout=120.0) as client:
        for trade_date in targets:
            payload = {"market": market_upper, "date": trade_date.isoformat()}
            try:
                response = client.post(f"{_packager_url()}/snapshots/build", json=payload)
                response.raise_for_status()
                body = response.json()
                typer.echo(
                    f"  {trade_date}  ok  {body.get('blob_uri', '')}  "
                    f"id={body.get('snapshot_id', '')}"
                )
                ok += 1
            except httpx.HTTPError as exc:
                failed += 1
                typer.echo(f"  {trade_date}  FAILED  {exc}", err=True)

    typer.echo(f"Done: {ok} succeeded, {failed} failed (expected ~22 files per calendar month).")
    if failed:
        raise typer.Exit(code=1)


@app.command("verify")
def verify(
    market: str = typer.Option(..., "--market", "-m", help="Market code"),
    target_date: str = typer.Option(..., "--date", help="Trade date YYYY-MM-DD"),
) -> None:
    """Re-fetch MinIO blob, validate schema v1, and compare SHA-256 to Postgres catalog."""
    market_upper = market.upper()
    trade_date = date.fromisoformat(target_date)

    async def _run() -> dict[str, Any]:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT blob_uri, blob_sha256, snapshot_id
                      FROM theeyebeta.data_snapshots_packaged
                     WHERE market = $1
                       AND trade_date = $2
                       AND schema_version = $3
                    """,
                    market_upper,
                    trade_date,
                    PACKAGED_SCHEMA_VERSION,
                )
            if row is None:
                msg = f"No catalog row for {market_upper} {trade_date}"
                raise typer.BadParameter(msg)

            payload_bytes = await asyncio.to_thread(_fetch_blob_bytes, market_upper, trade_date)
            payload = json.loads(payload_bytes.decode("utf-8"))
            validate_snapshot(payload)
            digest = hashlib.sha256(payload_bytes).hexdigest()
            catalog_hex = row["blob_sha256"].hex()
            if digest != catalog_hex:
                msg = (
                    f"SHA-256 mismatch for {market_upper} {trade_date}: "
                    f"blob={digest} catalog={catalog_hex}"
                )
                raise SnapshotValidationError(msg)
            return {
                "blob_uri": row["blob_uri"],
                "snapshot_id": str(row["snapshot_id"]),
                "sha256": digest,
            }
        finally:
            await pool.close()

    try:
        result = asyncio.run(_run())
    except SnapshotValidationError as exc:
        typer.echo(f"VERIFY FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"OK  {market_upper} {trade_date}  sha256={result['sha256'][:16]}...  "
        f"id={result['snapshot_id']}  uri={result['blob_uri']}"
    )
