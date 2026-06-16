#!/usr/bin/env python3
"""Detect stale worker heartbeats and write CRITICAL audit_alerts.

Runs every 15 minutes via ``theeye-heartbeat-monitor.timer``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import structlog
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
sys.path.insert(0, str(REPO_ROOT / "services" / "admin_service"))

from lib.worker_registry import (  # noqa: E402
    DEFAULT_HEARTBEAT_INTERVAL,
    WORKER_HEARTBEAT_INTERVALS,
)

log = structlog.get_logger()
STALE_MULTIPLIER = 2


async def run_monitor() -> int:
    """Return count of newly created CRITICAL alerts."""
    dsn = os.environ.get(
        "ADMIN_DATABASE_URL",
        os.environ.get("DATABASE_URL", ""),
    )
    if not dsn:
        log.error("heartbeat_monitor_no_dsn")
        return 1

    conn = await asyncpg.connect(dsn.replace("+asyncpg", ""))
    try:
        rows = await conn.fetch(
            """
            SELECT worker_id, last_heartbeat
              FROM theeyebeta.worker_heartbeats
            """,
        )
        now = datetime.now(tz=UTC)
        created = 0
        for row in rows:
            worker_id = row["worker_id"]
            expected = WORKER_HEARTBEAT_INTERVALS.get(worker_id, DEFAULT_HEARTBEAT_INTERVAL)
            last_hb = row["last_heartbeat"]
            stale = last_hb is None
            if last_hb is not None:
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=UTC)
                age = (now - last_hb).total_seconds()
                stale = age > expected * STALE_MULTIPLIER
            if not stale:
                continue

            title = f"Stale heartbeat: {worker_id}"
            existing = await conn.fetchval(
                """
                SELECT alert_id FROM theeyebeta.audit_alerts
                 WHERE worker_name = $1 AND title = $2
                   AND severity = 'CRITICAL' AND resolved_at IS NULL
                 LIMIT 1
                """,
                worker_id,
                title,
            )
            if existing:
                continue

            await conn.execute(
                """
                INSERT INTO theeyebeta.audit_alerts
                    (severity, worker_name, title, message, created_at)
                VALUES ('CRITICAL', $1, $2, $3, now())
                """,
                worker_id,
                title,
                f"last_heartbeat={last_hb}, expected_interval={expected}s",
            )
            created += 1
            log.warning("heartbeat_stale_alert", worker=worker_id, last_hb=last_hb)
        log.info("heartbeat_monitor_done", alerts_created=created, workers_checked=len(rows))
        return 0
    finally:
        await conn.close()


def main() -> None:
    """CLI entry."""
    raise SystemExit(asyncio.run(run_monitor()))


if __name__ == "__main__":
    main()
