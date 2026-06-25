"""Command run persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from db_compat import table_exists


class CommandRepository:
    """Store command previews and execution results."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def _runs_available(self) -> bool:
        return await table_exists(self._conn, "theeyebeta", "admin_command_runs")

    async def create_run(
        self,
        *,
        command_id: str,
        command_text: str,
        actor: str,
        reason: str | None,
        status: str,
        backend_route: str,
        audit_category: str,
        preview: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> UUID:
        if not await self._runs_available():
            return uuid4()
        run_id = await self._conn.fetchval(
            """
            INSERT INTO theeyebeta.admin_command_runs (
              command_id, command_text, actor, reason, status,
              preview, result, backend_route, audit_category, error, completed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10,
                    CASE WHEN $5 IN ('succeeded','failed','rejected') THEN now() ELSE NULL END)
            RETURNING id
            """,
            command_id,
            command_text,
            actor,
            reason,
            status,
            json.dumps(preview or {}, default=str),
            json.dumps(result or {}, default=str),
            backend_route,
            audit_category,
            error,
        )
        return UUID(str(run_id))

    async def complete_run(
        self,
        run_id: UUID,
        *,
        status: str,
        result: dict[str, Any],
        error: str | None = None,
    ) -> None:
        if not await self._runs_available():
            return
        await self._conn.execute(
            """
            UPDATE theeyebeta.admin_command_runs
               SET status = $2,
                   result = $3::jsonb,
                   error = $4,
                   completed_at = now()
             WHERE id = $1
            """,
            run_id,
            status,
            json.dumps(result, default=str),
            error,
        )

    async def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not await self._runs_available():
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, command_id, command_text, actor, reason, status,
                   preview, result, backend_route, audit_category, error,
                   created_at, completed_at
              FROM theeyebeta.admin_command_runs
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        if not await self._runs_available():
            return None
        row = await self._conn.fetchrow(
            """
            SELECT id, command_id, command_text, actor, reason, status,
                   preview, result, backend_route, audit_category, error,
                   created_at, completed_at
              FROM theeyebeta.admin_command_runs
             WHERE id = $1
            """,
            run_id,
        )
        return dict(row) if row else None

    async def latest_snapshot_id(self) -> str | None:
        if not await table_exists(self._conn, "theeyebeta", "data_snapshots_packaged"):
            return None
        val = await self._conn.fetchval(
            """
            SELECT snapshot_id::text
              FROM theeyebeta.data_snapshots_packaged
             ORDER BY packaged_at DESC
             LIMIT 1
            """,
        )
        return str(val) if val else None
