"""Session-scoped fixtures for the paper-trade smoke test suite.

Requires a fully running stack (make up) and valid Alpaca paper credentials.
All infrastructure URLs are read from environment variables with defaults
matching the production port map in docs/architecture.md §2.2.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_SRC = _ROOT / "services" / "snapshot_packager" / "src"

if str(_SNAPSHOT_SRC) not in sys.path:
    sys.path.insert(0, str(_SNAPSHOT_SRC))

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_OMS_URL = os.environ.get("OMS_URL", "http://127.0.0.1:8009")
_AUDIT_URL = os.environ.get("AUDIT_URL", "http://127.0.0.1:7110")
_MO_URL = os.environ.get("MO_URL", "http://127.0.0.1:8006")
_BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:7090")


def _clean_dsn(url: str) -> str:
    """Strip SQLAlchemy driver prefixes for plain asyncpg / psycopg usage."""
    return (
        url.replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+psycopg2://", "postgresql://", 1)
    )


@pytest.fixture(scope="session", autouse=True)
def require_stack() -> None:
    """Skip the entire session if any core service health check fails."""
    endpoints = {
        "oms": f"{_OMS_URL}/health",
        "audit": f"{_AUDIT_URL}/health",
        "master-orchestrator": f"{_MO_URL}/health",
        "broker-adapter": f"{_BROKER_URL}/health",
    }
    failed: list[str] = []
    with httpx.Client(timeout=5.0) as client:
        for name, url in endpoints.items():
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    failed.append(f"{name} returned {resp.status_code}")
            except httpx.ConnectError:
                failed.append(f"{name} unreachable at {url}")
    if failed:
        pytest.skip(f"Stack not ready — {'; '.join(failed)}")


@pytest.fixture(scope="session", autouse=True)
def require_alpaca_credentials() -> None:
    """Skip the entire session if Alpaca paper credentials are absent."""
    if not os.environ.get("ALPACA_API_KEY_PAPER"):
        pytest.skip("ALPACA_API_KEY_PAPER not set — skipping paper smoke test")


@pytest.fixture(scope="session")
def paper_smoke_date() -> date:
    """Most recent weekday ≤ today (UTC) — the trading date to exercise."""
    today = datetime.now(tz=UTC).date()
    while today.weekday() >= 5:  # Saturday=5, Sunday=6
        today -= timedelta(days=1)
    return today


@pytest.fixture(scope="session")
async def fast_forward_snapshot(paper_smoke_date: date) -> tuple[str, str]:
    """Return (snapshot_id, blob_uri) for the smoke trade date.

    Prefers an already-packaged snapshot in the DB.  Falls back to
    calling ``package_snapshot`` (requires MinIO to be running) so the
    test can proceed even when the nightly packager hasn't run yet.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    dsn = _clean_dsn(_DATABASE_URL)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        row = await pool.fetchrow(
            """
            SELECT snapshot_id::text, blob_uri
              FROM theeyebeta.data_snapshots_packaged
             WHERE market = $1 AND trade_date = $2
             ORDER BY packaged_at DESC
             LIMIT 1
            """,
            "US",
            paper_smoke_date,
        )
        if row:
            return str(row["snapshot_id"]), str(row["blob_uri"])

        try:
            from snapshot_packager.package import package_snapshot  # noqa: PLC0415
        except ImportError as exc:
            pytest.skip(f"snapshot_packager not importable and no cached snapshot: {exc}")

        try:
            result = await package_snapshot(pool, "US", paper_smoke_date)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"package_snapshot failed (is MinIO up?): {exc}")

        return str(result.snapshot_id), result.blob_uri
    finally:
        await pool.close()
