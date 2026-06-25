"""Database reads for worker runs, heartbeats, and control state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from db_compat import table_exists

log = structlog.get_logger()


class WorkersRepository:
    """Persisted control state + audit table reads."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._audit_available: bool | None = None
        self._heartbeat_available: bool | None = None
        self._control_available: bool | None = None

    async def audit_tables_available(self) -> bool:
        if self._audit_available is not None:
            return self._audit_available
        row = await self._conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'audit_worker_runs'
            )
            """,
        )
        self._audit_available = bool(row)
        return self._audit_available

    async def heartbeat_table_available(self) -> bool:
        if self._heartbeat_available is not None:
            return self._heartbeat_available
        row = await self._conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'worker_heartbeats'
            )
            """,
        )
        self._heartbeat_available = bool(row)
        return self._heartbeat_available

    async def control_table_available(self) -> bool:
        if self._control_available is not None:
            return self._control_available
        self._control_available = await table_exists(
            self._conn,
            "theeyebeta",
            "admin_worker_control",
        )
        return self._control_available

    async def fetch_last_runs(
        self,
        worker_names: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not worker_names or not await self.audit_tables_available():
            return {}
        rows = await self._conn.fetch(
            """
            SELECT DISTINCT ON (worker_name)
                   run_id, worker_name, worker_type, trade_date, run_type, status,
                   started_at, ended_at, duration_seconds, records_written,
                   records_expected, error_message
              FROM public.audit_worker_runs
             WHERE worker_name = ANY($1::text[])
             ORDER BY worker_name, started_at DESC
            """,
            list(worker_names),
        )
        return {str(row["worker_name"]): dict(row) for row in rows}

    async def fetch_recent_failures(
        self,
        worker_names: tuple[str, ...],
        *,
        limit: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        if not worker_names or not await self.audit_tables_available():
            return {}
        rows = await self._conn.fetch(
            """
            SELECT run_id, worker_name, worker_type, trade_date, run_type, status,
                   started_at, ended_at, duration_seconds, records_written,
                   records_expected, error_message
              FROM public.audit_worker_runs
             WHERE worker_name = ANY($1::text[])
               AND status = 'FAILED'
             ORDER BY started_at DESC
             LIMIT $2
            """,
            list(worker_names),
            limit,
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            name = str(row["worker_name"])
            out.setdefault(name, []).append(dict(row))
        return out

    async def fetch_runs(
        self,
        worker_names: tuple[str, ...],
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not worker_names or not await self.audit_tables_available():
            return []
        rows = await self._conn.fetch(
            """
            SELECT run_id, worker_name, worker_type, trade_date, run_type, status,
                   started_at, ended_at, duration_seconds, records_written,
                   records_expected, error_message, error_class
              FROM public.audit_worker_runs
             WHERE worker_name = ANY($1::text[])
             ORDER BY started_at DESC
             LIMIT $2
            """,
            list(worker_names),
            limit,
        )
        return [dict(row) for row in rows]

    async def fetch_run_by_id(self, run_id: int) -> dict[str, Any] | None:
        if not await self.audit_tables_available():
            return None
        row = await self._conn.fetchrow(
            """
            SELECT run_id, worker_name, worker_type, trade_date, run_type, status,
                   started_at, ended_at, duration_seconds, records_written,
                   records_expected, error_message, error_class, error_stack
              FROM public.audit_worker_runs
             WHERE run_id = $1
            """,
            run_id,
        )
        return dict(row) if row else None

    async def fetch_heartbeats(
        self,
        worker_ids: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not worker_ids or not await self.heartbeat_table_available():
            return {}
        rows = await self._conn.fetch(
            """
            SELECT worker_id, worker_type, status, last_heartbeat, started_at, last_error
              FROM public.worker_heartbeats
             WHERE worker_id = ANY($1::text[])
            """,
            list(worker_ids),
        )
        return {str(row["worker_id"]): dict(row) for row in rows}

    async def get_control_state(self, name: str) -> dict[str, Any] | None:
        if not await self.control_table_available():
            return None
        row = await self._conn.fetchrow(
            """
            SELECT name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
              FROM theeyebeta.admin_worker_control
             WHERE name = $1
            """,
            name,
        )
        return dict(row) if row else None

    async def list_control_states(self) -> dict[str, dict[str, Any]]:
        if not await self.control_table_available():
            return {}
        rows = await self._conn.fetch(
            """
            SELECT name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
              FROM theeyebeta.admin_worker_control
            """,
        )
        return {str(row["name"]): dict(row) for row in rows}

    async def ensure_control_row(
        self,
        name: str,
        kind: str,
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_worker_control (name, kind, updated_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (name) DO UPDATE SET updated_at = now()
            RETURNING name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
            """,
            name,
            kind,
            updated_by,
        )
        assert row is not None
        return dict(row)

    async def set_paused(
        self,
        name: str,
        paused: bool,
        *,
        updated_by: str,
    ) -> dict[str, Any]:
        await self.ensure_control_row(name, "worker", updated_by=updated_by)
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_worker_control
               SET paused = $2, updated_at = now(), updated_by = $3
             WHERE name = $1
            RETURNING name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
            """,
            name,
            paused,
            updated_by,
        )
        assert row is not None
        return dict(row)

    async def set_timer_enabled(
        self,
        name: str,
        enabled: bool,
        *,
        updated_by: str,
    ) -> dict[str, Any]:
        await self.ensure_control_row(name, "timer", updated_by=updated_by)
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_worker_control
               SET enabled = $2, updated_at = now(), updated_by = $3
             WHERE name = $1
            RETURNING name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
            """,
            name,
            enabled,
            updated_by,
        )
        assert row is not None
        return dict(row)

    async def patch_config(
        self,
        name: str,
        config: dict[str, Any],
        *,
        updated_by: str,
    ) -> dict[str, Any]:
        await self.ensure_control_row(name, "worker", updated_by=updated_by)
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_worker_control
               SET config = $2::jsonb, updated_at = now(), updated_by = $3
             WHERE name = $1
            RETURNING name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
            """,
            name,
            config,
            updated_by,
        )
        assert row is not None
        return dict(row)

    async def patch_schedule(
        self,
        name: str,
        schedule: str,
        *,
        updated_by: str,
    ) -> dict[str, Any]:
        await self.ensure_control_row(name, "timer", updated_by=updated_by)
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_worker_control
               SET schedule_override = $2, updated_at = now(), updated_by = $3
             WHERE name = $1
            RETURNING name, kind, paused, enabled, schedule_override, config, updated_at, updated_by
            """,
            name,
            schedule,
            updated_by,
        )
        assert row is not None
        return dict(row)

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)
