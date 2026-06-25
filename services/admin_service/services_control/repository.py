"""Persist operator actions against allowlisted services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg

from db_compat import table_exists


class ServicesRepository:
    """Action history for the services control plane."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def _actions_available(self) -> bool:
        return await table_exists(self._conn, "theeyebeta", "admin_service_actions")

    async def record_action(
        self,
        *,
        service_name: str,
        action: str,
        actor: str,
        reason: str,
        status: str,
        message: str,
    ) -> dict[str, Any]:
        if not await self._actions_available():
            return {
                "id": 0,
                "service_name": service_name,
                "action": action,
                "actor": actor,
                "reason": reason,
                "status": status,
                "message": message[:2000],
                "created_at": self.utc_now(),
            }
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_service_actions
                (service_name, action, actor, reason, status, message)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, service_name, action, actor, reason, status, message, created_at
            """,
            service_name,
            action,
            actor,
            reason,
            status,
            message[:2000],
        )
        assert row is not None
        return dict(row)

    async def list_history(
        self,
        service_name: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not await self._actions_available():
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, service_name, action, actor, reason, status, message, created_at
              FROM theeyebeta.admin_service_actions
             WHERE service_name = $1
             ORDER BY created_at DESC
             LIMIT $2
            """,
            service_name,
            limit,
        )
        return [dict(row) for row in rows]

    async def last_action(self, service_name: str) -> dict[str, Any] | None:
        if not await self._actions_available():
            return None
        row = await self._conn.fetchrow(
            """
            SELECT id, service_name, action, actor, reason, status, message, created_at
              FROM theeyebeta.admin_service_actions
             WHERE service_name = $1
             ORDER BY created_at DESC
             LIMIT 1
            """,
            service_name,
        )
        return dict(row) if row else None
