"""Database access for trading halt, approval, and event history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

from db_compat import table_exists


_DEFAULT_STATE: dict[str, Any] = {
    "live_trading_enabled": False,
    "emergency_halt": False,
    "broker_mode": "paper",
    "last_halt_reason": None,
    "last_halt_at": None,
    "last_halt_by": None,
    "last_resume_reason": None,
    "last_resume_at": None,
    "last_resume_by": None,
    "last_operator": None,
    "updated_at": None,
}


class TradingRepository:
    """Persisted trading control state."""

    OMS_PAUSE_KEY = "oms:submissions_paused"

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def get_state(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_trading_state"):
            return dict(_DEFAULT_STATE)
        row = await self._conn.fetchrow(
            """
            SELECT live_trading_enabled, emergency_halt, broker_mode,
                   last_halt_reason, last_halt_at, last_halt_by,
                   last_resume_reason, last_resume_at, last_resume_by,
                   last_operator, updated_at
              FROM theeyebeta.admin_trading_state
             WHERE id = 1
            """,
        )
        if row is None:
            await self._conn.execute(
                "INSERT INTO theeyebeta.admin_trading_state (id) VALUES (1) ON CONFLICT DO NOTHING",
            )
            row = await self._conn.fetchrow(
                "SELECT * FROM theeyebeta.admin_trading_state WHERE id = 1",
            )
        assert row is not None
        return dict(row)

    async def save_state(self, **fields: Any) -> dict[str, Any]:
        if not fields:
            return await self.get_state()
        if not await table_exists(self._conn, "theeyebeta", "admin_trading_state"):
            state = dict(_DEFAULT_STATE)
            state.update(fields)
            state["updated_at"] = self.utc_now()
            return state
        sets = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(fields, start=1))
        values = list(fields.values())
        row = await self._conn.fetchrow(
            f"""
            UPDATE theeyebeta.admin_trading_state
               SET {sets}, updated_at = now()
             WHERE id = 1
            RETURNING live_trading_enabled, emergency_halt, broker_mode,
                      last_halt_reason, last_halt_at, last_halt_by,
                      last_resume_reason, last_resume_at, last_resume_by,
                      last_operator, updated_at
            """,
            *values,
        )
        assert row is not None
        return dict(row)

    async def insert_token(
        self,
        *,
        token_hash: str,
        issued_by: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_live_approval_tokens
                (token_hash, issued_by, expires_at)
            VALUES ($1, $2, $3)
            RETURNING token_id, issued_at, expires_at
            """,
            token_hash,
            issued_by,
            expires_at,
        )
        assert row is not None
        return dict(row)

    async def consume_token(self, token_hash: str, *, consumed_by: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_live_approval_tokens
               SET consumed_at = now(), consumed_by = $2
             WHERE token_hash = $1
               AND consumed_at IS NULL
               AND expires_at > now()
            RETURNING token_id, issued_at, expires_at, consumed_at
            """,
            token_hash,
            consumed_by,
        )
        return dict(row) if row else None

    async def pending_token_summary(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_live_approval_tokens"):
            return {"pending": 0, "last_issued_at": None, "next_expiry": None}
        row = await self._conn.fetchrow(
            """
            SELECT COUNT(*)::int AS pending,
                   MAX(issued_at) AS last_issued_at,
                   MIN(expires_at) FILTER (WHERE expires_at > now()) AS next_expiry
              FROM theeyebeta.admin_live_approval_tokens
             WHERE consumed_at IS NULL
               AND expires_at > now()
            """,
        )
        return dict(row or {"pending": 0, "last_issued_at": None, "next_expiry": None})

    async def grant_live_approval_on_accounts(self) -> int:
        result = await self._conn.execute(
            """
            UPDATE theeyebeta.accounts
               SET metadata = COALESCE(metadata, '{}'::jsonb)
                              || jsonb_build_object('live_approval', true)
             WHERE mode = 'live'
            """,
        )
        return int(result.split()[-1])

    async def ensure_live_account(self) -> None:
        await self._conn.execute(
            """
            INSERT INTO theeyebeta.accounts (external_id, broker, mode, metadata)
            VALUES ('terminal-live-account', 'alpaca', 'live', '{}'::jsonb)
            ON CONFLICT (external_id) DO NOTHING
            """,
        )

    async def live_approval_on_accounts(self) -> bool:
        row = await self._conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM theeyebeta.accounts
               WHERE mode = 'live'
                 AND COALESCE((metadata->>'live_approval')::boolean, false) = true
            )
            """,
        )
        return bool(row)

    async def record_event(
        self,
        *,
        event_type: str,
        actor: str,
        reason: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_trading_events
                (event_type, actor, reason, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id, event_type, actor, reason, payload, created_at
            """,
            event_type,
            actor,
            reason,
            json.dumps(payload, default=str),
        )
        assert row is not None
        return dict(row)

    async def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_trading_events"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_trading_events
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_gate_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_trading_events"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_trading_events
             WHERE event_type IN (
               'emergency_halt',
               'resume_from_halt',
               'live_approval',
               'oms_gate_pause',
               'oms_gate_resume'
             )
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]
