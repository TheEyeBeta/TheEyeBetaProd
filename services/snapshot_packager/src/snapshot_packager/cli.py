"""tb-snapshot CLI — build and inspect market-data snapshots."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path

import psycopg
import structlog
import typer
from dotenv import load_dotenv

from .builder import build_snapshot
from .writers import SNAPSHOT_DIR, record_in_db, write_local

load_dotenv()
log = structlog.get_logger()

app = typer.Typer(no_args_is_help=True, help="theeyebeta snapshot packager")

MARKETS = ["XNAS", "XNYS", "XSHG", "XSHE", "XTAI", "XTKS", "XHKG"]


def _db_url() -> str:
    """Return a psycopg-native connection URL from DATABASE_URL."""
    raw = os.environ["DATABASE_URL"]
    # Strip any SQLAlchemy driver suffix (+asyncpg, +psycopg, etc.)
    return re.sub(r"\+\w+", "", raw, count=1)


async def _build_one(market: str, target: date) -> dict:
    """Build, write, and record a single market snapshot."""
    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        snap = await build_snapshot(conn, market, target)
        path, digest = write_local(snap)
        await record_in_db(conn, snap, path, digest)
        return {
            "market": market,
            "trade_date": str(target),
            "universe": len(snap.universe),
            "path": str(path),
            "sha256": digest.hex()[:16] + "...",
        }


async def _build_all(mkts: list[str], target: date) -> list[dict]:
    return await asyncio.gather(*[_build_one(m, target) for m in mkts])


@app.command()
def build(
    market: str = typer.Option(
        ...,
        help="MIC code (XNAS, XNYS, XSHG, XSHE, XTAI, XTKS, XHKG) or 'all'",
    ),
    target_date: str = typer.Option(..., "--date", help="Trade date in YYYY-MM-DD"),
) -> None:
    """Build snapshots for one market (or all) on the given trade date."""
    target = date.fromisoformat(target_date)
    mkts = MARKETS if market == "all" else [market]
    log.info("build_start", markets=mkts, trade_date=str(target))
    results = asyncio.run(_build_all(mkts, target))
    for r in results:
        typer.echo(
            f"  {r['market']}  {r['trade_date']}"
            f"  universe={r['universe']:>3}"
            f"  sha256={r['sha256']}"
            f"  -> {r['path']}"
        )
    log.info("build_complete", count=len(results))


@app.command()
def show(
    market: str = typer.Argument(..., help="MIC code"),
    target_date: str = typer.Option(..., "--date", help="Trade date YYYY-MM-DD"),
) -> None:
    """Pretty-print a snapshot JSON to stdout."""
    p = SNAPSHOT_DIR / market / f"{target_date}.json"
    typer.echo(json.dumps(json.loads(p.read_text()), indent=2))
