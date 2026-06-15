"""Shared audit/heartbeat lifecycle for named workers."""

from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import asyncpg
import structlog

try:  # Local CLI runs should pick up .env; systemd uses EnvironmentFile.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is convenience only.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

log = structlog.get_logger()


def worker_database_url() -> str:
    """Return the DB URL used by operational workers."""
    raw = (
        os.environ.get("MACRO_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("INGEST_DATABASE_URL")
        or ""
    )
    if not raw:
        msg = "Set MACRO_DATABASE_URL, DATABASE_URL, or INGEST_DATABASE_URL"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


@dataclass(slots=True)
class WorkerResult:
    """Summary returned by a worker implementation."""

    records_written: int = 0
    records_expected: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseWorker:
    """Base class that guarantees terminal audit state for each real run."""

    worker_name = "BaseWorker"
    worker_type = "system"
    display_name: str | None = None

    def __init__(self, *, database_url: str | None = None) -> None:
        self.database_url = (
            (database_url or worker_database_url())
            .replace("+asyncpg", "")
            .replace(
                "+psycopg",
                "",
            )
        )
        self.run_id: int | None = None

    async def run(
        self,
        trade_date: date,
        *,
        run_type: str = "manual",
        dry_run: bool = False,
        records_expected: int | None = None,
    ) -> WorkerResult:
        """Run the worker with audit lifecycle wrapping.

        Dry runs intentionally write nothing, including no audit rows.
        """
        conn = await asyncpg.connect(self.database_url)
        try:
            if dry_run:
                return await self.execute(conn, trade_date, dry_run=True)

            self.run_id = await self._start_run(conn, trade_date, run_type, records_expected)
            await self._set_liveness(conn, component_state="RUNNING", heartbeat_status="running")
            try:
                result = await self.execute(conn, trade_date, dry_run=False)
            except Exception as exc:
                await self._finish_failed(conn, exc)
                await self._set_liveness(
                    conn,
                    component_state="FAILED",
                    heartbeat_status="failed",
                    last_error=str(exc),
                )
                raise

            await self._finish_completed(conn, result)
            await self._set_liveness(conn, component_state="STOPPED", heartbeat_status="stopped")
            return result
        finally:
            await conn.close()

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        """Implement worker-specific behavior in subclasses."""
        raise NotImplementedError

    async def _start_run(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        run_type: str,
        records_expected: int | None,
    ) -> int:
        insert_sql = """
            INSERT INTO theeyebeta.worker_runs
                (worker_name, worker_type, trade_date, run_type, status,
                 started_at, records_expected)
            VALUES ($1, $2, $3, $4, 'STARTED', now(), $5)
            RETURNING run_id
            """
        try:
            row = await conn.fetchrow(
                insert_sql,
                self.worker_name,
                self.worker_type,
                trade_date,
                run_type,
                records_expected,
            )
        except asyncpg.UniqueViolationError:
            if run_type != "scheduled":
                raise
            # audit_worker_runs_scheduled_unique_idx allows one scheduled row
            # per (worker_name, trade_date). A rerun of the same calendar day
            # must still execute and stay auditable, so register it as a
            # recovery run instead of crashing the whole systemd unit.
            log.warning(
                "scheduled_run_already_registered",
                worker_name=self.worker_name,
                trade_date=trade_date.isoformat(),
                fallback_run_type="recovery",
            )
            row = await conn.fetchrow(
                insert_sql,
                self.worker_name,
                self.worker_type,
                trade_date,
                "recovery",
                records_expected,
            )
        return int(row["run_id"])

    async def _finish_completed(self, conn: asyncpg.Connection, result: WorkerResult) -> None:
        if self.run_id is None:
            return
        await conn.execute(
            """
            UPDATE theeyebeta.worker_runs
               SET status = 'COMPLETED',
                   ended_at = now(),
                   duration_seconds = GREATEST(
                       0,
                       EXTRACT(EPOCH FROM (now() - started_at))::integer
                   ),
                   records_written = $2,
                   records_expected = COALESCE($3, records_expected),
                   metadata = $4::jsonb
             WHERE run_id = $1
            """,
            self.run_id,
            result.records_written,
            result.records_expected,
            json.dumps(result.metadata or {}),
        )

    async def _finish_failed(self, conn: asyncpg.Connection, exc: Exception) -> None:
        if self.run_id is None:
            return
        await conn.execute(
            """
            UPDATE theeyebeta.worker_runs
               SET status = 'FAILED',
                   ended_at = now(),
                   duration_seconds = GREATEST(
                       0,
                       EXTRACT(EPOCH FROM (now() - started_at))::integer
                   ),
                   records_failed = COALESCE(records_expected, 0),
                   error_class = $2,
                   error_message = $3,
                   error_stack = $4
             WHERE run_id = $1
            """,
            self.run_id,
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )

    async def _set_liveness(
        self,
        conn: asyncpg.Connection,
        *,
        component_state: str,
        heartbeat_status: str,
        last_error: str | None = None,
    ) -> None:
        display_name = self.display_name or self.worker_name
        metadata = json.dumps({"run_id": self.run_id})
        await conn.execute(
            """
            INSERT INTO theeyebeta.worker_heartbeats
                (worker_id, worker_type, status, last_heartbeat, started_at,
                 last_error, metadata)
            VALUES ($1, $2, $3, now(), now(), $4, $5::jsonb)
            ON CONFLICT (worker_id) DO UPDATE SET
                worker_type = EXCLUDED.worker_type,
                status = EXCLUDED.status,
                last_heartbeat = now(),
                last_error = EXCLUDED.last_error,
                metadata = EXCLUDED.metadata
            """,
            self.worker_name,
            self.worker_type,
            heartbeat_status,
            last_error,
            metadata,
        )
        await conn.execute(
            """
            INSERT INTO theeyebeta.trask_components
                (component_type, component_id, display_name, state, last_heartbeat,
                 config, metadata)
            VALUES ($1, $2, $3, $4, now(), '{}'::jsonb, $5::jsonb)
            ON CONFLICT (component_id) DO UPDATE SET
                component_type = EXCLUDED.component_type,
                display_name = EXCLUDED.display_name,
                state = EXCLUDED.state,
                last_heartbeat = now(),
                last_state_change = CASE
                    WHEN theeyebeta.trask_components.state <> EXCLUDED.state THEN now()
                    ELSE theeyebeta.trask_components.last_state_change
                END,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            """,
            self.worker_type,
            self.worker_name,
            display_name,
            component_state,
            metadata,
        )
