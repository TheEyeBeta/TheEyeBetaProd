"""tb-snapshot CLI — build and inspect packaged market snapshots."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date

import asyncpg
import structlog
import typer
from dotenv import load_dotenv
from zinc_schemas.packaged_snapshot import PackagedSnapshotV1

from snapshot_packager.builder import SnapshotBuilder
from snapshot_packager.markets import VALID_MARKETS
from snapshot_packager.writers import PackagedSnapshotWriter

load_dotenv()
log = structlog.get_logger()

app = typer.Typer(no_args_is_help=True, help="theeyebeta snapshot packager")

MARKETS = sorted(VALID_MARKETS)


def _db_url() -> str:
    """Return an asyncpg-compatible connection URL."""
    raw = os.environ.get("INGEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    return re.sub(r"\+\w+", "", raw, count=1)


async def _build_one(market: str, target: date) -> dict[str, object]:
    """Build, upload, and record a single packaged snapshot."""
    pool = await asyncpg.create_pool(_db_url(), min_size=1, max_size=4)
    try:
        builder = SnapshotBuilder(pool)
        raw = await builder.build(market, target)
        snapshot = PackagedSnapshotV1.model_validate(raw)
        writer = PackagedSnapshotWriter()
        result = await writer.write_minio(snapshot)
        async with pool.acquire() as conn, conn.transaction():
            await writer.record_packaged(
                conn,
                snapshot=snapshot,
                result=result,
                trade_date=target,
            )
        return {
            "market": market,
            "trade_date": str(target),
            "universe": len(snapshot.universe),
            "blob_uri": result.blob_uri,
            "snapshot_id": str(snapshot.snapshot_id),
        }
    finally:
        await pool.close()


async def _build_all(mkts: list[str], target: date) -> list[dict[str, object]]:
    return await asyncio.gather(*[_build_one(m, target) for m in mkts])


@app.command()
def build(
    market: str = typer.Option(
        ...,
        help="Market code (US, HK, JP, TW, CN) or 'all'",
    ),
    target_date: str = typer.Option(..., "--date", help="Trade date in YYYY-MM-DD"),
) -> None:
    """Build packaged snapshots for one market (or all) on the given trade date."""
    target = date.fromisoformat(target_date)
    mkts = MARKETS if market == "all" else [market.upper()]
    log.info("build_start", markets=mkts, trade_date=str(target))
    results = asyncio.run(_build_all(mkts, target))
    for row in results:
        typer.echo(
            f"  {row['market']}  {row['trade_date']}"
            f"  universe={row['universe']:>3}"
            f"  id={row['snapshot_id']}"
            f"  -> {row['blob_uri']}"
        )
    log.info("build_complete", count=len(results))


@app.command()
def show(
    market: str = typer.Argument(..., help="Market code (US, HK, ...)"),
    target_date: str = typer.Option(..., "--date", help="Trade date YYYY-MM-DD"),
) -> None:
    """Fetch packaged snapshot JSON from MinIO and print it."""
    from minio import Minio

    target = date.fromisoformat(target_date)
    market_upper = market.upper()
    key = f"packaged/{market_upper}/{target.year:04d}/{target.month:02d}/{target.isoformat()}.json"
    endpoint = os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")
    host = endpoint.replace("http://", "").replace("https://", "")
    client = Minio(
        host,
        access_key=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.environ.get("MINIO_ROOT_PASSWORD", ""),
        secure=endpoint.startswith("https://"),
    )
    bucket = os.environ.get("MINIO_SNAPSHOT_BUCKET", "theeyebeta-snapshots")
    payload = client.get_object(bucket, key).read()
    typer.echo(json.dumps(json.loads(payload), indent=2))
