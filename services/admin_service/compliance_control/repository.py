"""Compliance cockpit database reads and writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from db_compat import column_exists, table_exists
from compliance_control.registry import DEFAULT_RULES


class ComplianceRepository:
    """Compliance checks, rules overlay, exceptions, legal holds, events."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def default_portfolio_id(self) -> str | None:
        row = await self._conn.fetchval(
            """
            SELECT id::text FROM theeyebeta.portfolios
             ORDER BY created_at ASC NULLS LAST
             LIMIT 1
            """,
        )
        return str(row) if row else None

    async def default_instrument_id(self) -> int | None:
        row = await self._conn.fetchval(
            """
            SELECT id FROM theeyebeta.instruments
             WHERE active
             ORDER BY symbol ASC
             LIMIT 1
            """,
        )
        return int(row) if row is not None else None

    async def get_rules_row(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_compliance_rules"):
            return {"version": 1, "rules": DEFAULT_RULES, "updated_at": None, "updated_by": None}
        row = await self._conn.fetchrow(
            """
            SELECT version, rules, updated_at, updated_by
              FROM theeyebeta.admin_compliance_rules
             WHERE id = 1
            """,
        )
        if row is None:
            return {"version": 1, "rules": DEFAULT_RULES, "updated_at": None, "updated_by": None}
        rules = row["rules"]
        if isinstance(rules, str):
            rules = json.loads(rules)
        merged = {**DEFAULT_RULES, **(rules or {})}
        return {
            "version": int(row["version"]),
            "rules": merged,
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    async def patch_rules(self, rules: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        current = await self.get_rules_row()
        merged = {**current["rules"], **rules}
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_compliance_rules
               SET rules = $1::jsonb,
                   version = version + 1,
                   updated_at = now(),
                   updated_by = $2
             WHERE id = 1
            RETURNING version, rules, updated_at, updated_by
            """,
            json.dumps(merged, default=str),
            updated_by,
        )
        assert row is not None
        return {
            "version": int(row["version"]),
            "rules": dict(row["rules"]),
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    async def portfolio_mandate_rules(self, portfolio_id: str) -> dict[str, Any]:
        row = await self._conn.fetchval(
            "SELECT mandate FROM theeyebeta.portfolios WHERE id = $1::uuid",
            UUID(portfolio_id),
        )
        if row is None:
            return DEFAULT_RULES.copy()
        mandate = row if isinstance(row, dict) else json.loads(row or "{}")
        compliance_raw = mandate.get("compliance") if isinstance(mandate, dict) else {}
        if not compliance_raw:
            compliance_raw = mandate
        return {**DEFAULT_RULES, **(compliance_raw or {})}

    async def get_state(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_compliance_state"):
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT last_recheck_at, last_recheck_by, last_recheck_portfolio_id, updated_at
              FROM theeyebeta.admin_compliance_state
             WHERE id = 1
            """,
        )
        return dict(row) if row else {}

    async def save_state(self, **fields: Any) -> dict[str, Any]:
        if not fields:
            return await self.get_state()
        sets = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(fields, start=1))
        row = await self._conn.fetchrow(
            f"""
            UPDATE theeyebeta.admin_compliance_state
               SET {sets}, updated_at = now()
             WHERE id = 1
            RETURNING last_recheck_at, last_recheck_by, last_recheck_portfolio_id, updated_at
            """,
            *fields.values(),
        )
        assert row is not None
        return dict(row)

    async def list_checks(self, *, limit: int = 50, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "compliance_checks"):
            return []
        if portfolio_id:
            rows = await self._conn.fetch(
                """
                SELECT id, order_id, portfolio_id, rule_id, outcome, detail, checked_at
                  FROM theeyebeta.compliance_checks
                 WHERE portfolio_id = $1::uuid
                 ORDER BY checked_at DESC
                 LIMIT $2
                """,
                UUID(portfolio_id),
                limit,
            )
        else:
            rows = await self._conn.fetch(
                """
                SELECT id, order_id, portfolio_id, rule_id, outcome, detail, checked_at
                  FROM theeyebeta.compliance_checks
                 ORDER BY checked_at DESC
                 LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def list_failed_checks(
        self,
        *,
        limit: int = 50,
        portfolio_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "compliance_checks"):
            return []
        if portfolio_id:
            rows = await self._conn.fetch(
                """
                SELECT id, order_id, portfolio_id, rule_id, outcome, detail, checked_at
                  FROM theeyebeta.compliance_checks
                 WHERE portfolio_id = $1::uuid
                   AND outcome IN ('block', 'warn')
                 ORDER BY checked_at DESC
                 LIMIT $2
                """,
                UUID(portfolio_id),
                limit,
            )
        else:
            rows = await self._conn.fetch(
                """
                SELECT id, order_id, portfolio_id, rule_id, outcome, detail, checked_at
                  FROM theeyebeta.compliance_checks
                 WHERE outcome IN ('block', 'warn')
                 ORDER BY checked_at DESC
                 LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def insert_override(
        self,
        *,
        portfolio_id: str | None,
        rule_id: str,
        reason: str,
        actor: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_compliance_overrides
                (portfolio_id, rule_id, reason, actor, expires_at)
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id, portfolio_id, rule_id, reason, actor, expires_at, active, created_at
            """,
            UUID(portfolio_id) if portfolio_id else None,
            rule_id,
            reason,
            actor,
            expires_at,
        )
        assert row is not None
        return dict(row)

    async def list_overrides(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_compliance_overrides"):
            return []
        clause = "WHERE active AND (expires_at IS NULL OR expires_at > now())" if active_only else ""
        rows = await self._conn.fetch(
            f"""
            SELECT id, portfolio_id, rule_id, reason, actor, expires_at, active, created_at
              FROM theeyebeta.admin_compliance_overrides
              {clause}
             ORDER BY created_at DESC
             LIMIT 100
            """,
        )
        return [dict(row) for row in rows]

    async def insert_exception(
        self,
        *,
        portfolio_id: str | None,
        rule_id: str,
        reason: str,
        actor: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_compliance_exceptions
                (portfolio_id, rule_id, reason, actor, expires_at)
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id, portfolio_id, rule_id, reason, actor, expires_at, active, created_at
            """,
            UUID(portfolio_id) if portfolio_id else None,
            rule_id,
            reason,
            actor,
            expires_at,
        )
        assert row is not None
        return dict(row)

    async def list_exceptions(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_compliance_exceptions"):
            return []
        clause = "WHERE active AND (expires_at IS NULL OR expires_at > now())" if active_only else ""
        rows = await self._conn.fetch(
            f"""
            SELECT id, portfolio_id, rule_id, reason, actor, expires_at, active, created_at
              FROM theeyebeta.admin_compliance_exceptions
              {clause}
             ORDER BY created_at DESC
             LIMIT 100
            """,
        )
        return [dict(row) for row in rows]

    async def apply_legal_hold(
        self,
        *,
        entity_type: str,
        entity_id: str,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        await self._conn.execute(
            """
            UPDATE theeyebeta.admin_legal_holds
               SET active = false, released_at = now(), released_by = $3
             WHERE entity_type = $1 AND entity_id = $2 AND active
            """,
            entity_type,
            entity_id,
            actor,
        )
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_legal_holds
                (entity_type, entity_id, reason, placed_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id, entity_type, entity_id, reason, placed_by, placed_at, released_by, released_at, active
            """,
            entity_type,
            entity_id,
            reason,
            actor,
        )
        assert row is not None
        return dict(row)

    async def release_legal_hold(
        self,
        *,
        entity_type: str,
        entity_id: str,
        actor: str,
    ) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_legal_holds
               SET active = false, released_at = now(), released_by = $3
             WHERE entity_type = $1 AND entity_id = $2 AND active
            RETURNING id, entity_type, entity_id, reason, placed_by, placed_at, released_by, released_at, active
            """,
            entity_type,
            entity_id,
            actor,
        )
        return dict(row) if row else None

    async def list_legal_holds(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_legal_holds"):
            return []
        clause = "WHERE active" if active_only else ""
        rows = await self._conn.fetch(
            f"""
            SELECT id, entity_type, entity_id, reason, placed_by, placed_at,
                   released_by, released_at, active
              FROM theeyebeta.admin_legal_holds
              {clause}
             ORDER BY placed_at DESC
             LIMIT 100
            """,
        )
        return [dict(row) for row in rows]

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
            INSERT INTO theeyebeta.admin_compliance_events
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

    async def list_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_compliance_events"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_compliance_events
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def unresolved_guard_violations(self) -> int:
        if not await table_exists(self._conn, "theeyebeta", "guard_violations"):
            return 0
        if await column_exists(self._conn, "theeyebeta", "guard_violations", "resolved_at"):
            return int(
                await self._conn.fetchval(
                    """
                    SELECT COUNT(*) FROM theeyebeta.guard_violations
                     WHERE resolved_at IS NULL
                    """,
                )
                or 0,
            )
        return int(
            await self._conn.fetchval("SELECT COUNT(*) FROM theeyebeta.guard_violations") or 0
        )
