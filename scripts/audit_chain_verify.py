#!/usr/bin/env python3
"""Daily audit hash-chain verification; persists result to audit_chain_status."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
import structlog
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

log = structlog.get_logger()


async def run_verify() -> int:
    """Verify last 24h of audit chain via audit-service."""
    audit_url = os.environ.get("AUDIT_SERVICE_URL", "http://127.0.0.1:7110").rstrip("/")
    dsn = os.environ.get(
        "ADMIN_DATABASE_URL",
        os.environ.get("DATABASE_URL", ""),
    )
    if not dsn:
        log.error("audit_verify_no_dsn")
        return 1

    to_ts = datetime.now(tz=UTC)
    from_ts = to_ts - timedelta(hours=24)
    valid = False
    entries_checked = 0
    first_invalid: int | None = None
    error_message: str | None = None

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                f"{audit_url}/audit/verify",
                params={"from": from_ts.isoformat(), "to": to_ts.isoformat()},
            )
        if resp.status_code != 200:
            error_message = f"audit-service returned {resp.status_code}: {resp.text[:500]}"
        else:
            data = resp.json()
            valid = str(data.get("status", "")).upper() == "OK"
            entries_checked = int(data.get("rows_checked", 0))
            bad = data.get("first_bad_row_id")
            first_invalid = int(bad) if bad is not None else None
            if not valid:
                error_message = str(data.get("detail", "chain verification failed"))
    except httpx.HTTPError as exc:
        error_message = str(exc)

    conn = await asyncpg.connect(dsn.replace("+asyncpg", ""))
    try:
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_chain_status
                (verified_at, valid, entries_checked, first_invalid_seq, error_message)
            VALUES (now(), $1, $2, $3, $4)
            """,
            valid,
            entries_checked,
            first_invalid,
            error_message,
        )
    finally:
        await conn.close()

    if error_message:
        log.error("audit_chain_verify_failed", error=error_message)
        return 1
    log.info("audit_chain_verify_ok", entries_checked=entries_checked)
    return 0


def main() -> None:
    """CLI entry."""
    raise SystemExit(asyncio.run(run_verify()))


if __name__ == "__main__":
    main()
