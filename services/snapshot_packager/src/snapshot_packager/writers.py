"""Snapshot persistence: local filesystem + theeyebeta.data_snapshots record."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

import psycopg

from zinc_schemas.snapshot import Snapshot

# Directory where JSON snapshot files are written.
# Override with the SNAPSHOT_DIR environment variable.
SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "./snapshots"))


def write_local(snapshot: Snapshot) -> tuple[Path, bytes]:
    """Serialise a snapshot to disk as UTF-8 JSON.

    Creates ``<SNAPSHOT_DIR>/<market>/<trade_date>.json``.

    Args:
        snapshot: The fully-populated :class:`Snapshot` to write.

    Returns:
        Tuple of (path written, SHA-256 digest of the raw bytes).
    """
    d = SNAPSHOT_DIR / snapshot.market
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{snapshot.trade_date}.json"
    payload = snapshot.model_dump_json(indent=2).encode("utf-8")
    digest = sha256(payload).digest()
    path.write_bytes(payload)
    return path, digest


async def record_in_db(
    conn: psycopg.AsyncConnection,  # type: ignore[type-arg]
    snapshot: Snapshot,
    path: Path,
    digest: bytes,
) -> None:
    """Upsert a data_snapshots row tracking the persisted snapshot file.

    Uses ON CONFLICT to allow idempotent re-packaging: re-running the build
    for the same (market, trade_date, schema_version) overwrites the row.

    Args:
        conn: Open psycopg3 async connection with INSERT/UPDATE on data_snapshots.
        snapshot: The snapshot whose metadata to record.
        path: Absolute filesystem path where the JSON was written.
        digest: SHA-256 digest bytes of the JSON payload.
    """
    await conn.execute(
        """
        INSERT INTO theeyebeta.data_snapshots
            (market, trade_date, schema_version, blob_uri,
             blob_sha256, universe_size, packager_git_sha)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (market, trade_date, schema_version) DO UPDATE
            SET blob_uri      = EXCLUDED.blob_uri,
                blob_sha256   = EXCLUDED.blob_sha256,
                universe_size = EXCLUDED.universe_size,
                packaged_at   = now()
        """,
        (
            snapshot.market,
            snapshot.trade_date,
            snapshot.schema_version,
            f"file://{path.resolve()}",
            digest,
            len(snapshot.universe),
            os.environ.get("GIT_COMMIT", "dev"),
        ),
    )
    await conn.commit()
