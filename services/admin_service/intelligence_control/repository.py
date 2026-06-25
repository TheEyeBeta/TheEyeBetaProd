"""Database access for intelligence control plane."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from db_compat import table_exists


class IntelligenceRepository:
    """Agents, proposals, backtests, reports, costs operator state."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def _briefings_available(self) -> bool:
        return await table_exists(self._conn, "theeyebeta", "admin_briefings")

    async def agent_row(self, agent_id: str) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            SELECT a.id, a.department, a.role, a.model_default, a.model_fallback,
                   a.constitution_path, a.active,
                   COALESCE(c.paused, false) AS paused
              FROM theeyebeta.agents a
              LEFT JOIN theeyebeta.admin_agent_control c ON c.agent_id = a.id
             WHERE a.id = $1
            """,
            agent_id,
        )

    async def agent_violation_count(self, agent_id: str) -> int:
        val = await self._conn.fetchval(
            """
            SELECT COUNT(*)::int FROM theeyebeta.guard_violations
             WHERE agent_id = $1 AND NOT resolved
            """,
            agent_id,
        )
        return int(val or 0)

    async def agent_cost_7d(self, agent_id: str) -> Decimal:
        val = await self._conn.fetchval(
            """
            SELECT COALESCE(SUM(mr.cost_usd), 0)
              FROM theeyebeta.agent_runs ar
              JOIN theeyebeta.model_runs mr ON mr.run_id = ar.id
             WHERE ar.agent_id = $1
               AND mr.created_at >= now() - interval '7 days'
            """,
            agent_id,
        )
        return Decimal(str(val or 0))

    async def set_agent_paused(self, agent_id: str, *, paused: bool, actor: str) -> None:
        await self._conn.execute(
            """
            INSERT INTO theeyebeta.admin_agent_control (agent_id, paused, updated_by, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (agent_id) DO UPDATE
               SET paused = EXCLUDED.paused,
                   updated_by = EXCLUDED.updated_by,
                   updated_at = now()
            """,
            agent_id,
            paused,
            actor,
        )

    async def set_agent_active(self, agent_id: str, *, active: bool) -> None:
        await self._conn.execute(
            """
            UPDATE theeyebeta.agents SET active = $2, updated_at = now() WHERE id = $1
            """,
            agent_id,
            active,
        )

    async def patch_agent_models(
        self,
        agent_id: str,
        *,
        model_default: str | None,
        model_fallback: str | None,
    ) -> asyncpg.Record | None:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.agents
               SET model_default = COALESCE($2, model_default),
                   model_fallback = COALESCE($3, model_fallback),
                   updated_at = now()
             WHERE id = $1
            RETURNING id, model_default, model_fallback, constitution_path, active
            """,
            agent_id,
            model_default,
            model_fallback,
        )
        return row

    async def list_agent_versions(self, agent_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT id, agent_id, label, constitution_path, content_hash, created_at, created_by
              FROM theeyebeta.admin_agent_versions
             WHERE agent_id = $1
             ORDER BY created_at DESC
             LIMIT $2
            """,
            agent_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def insert_agent_version(
        self,
        *,
        agent_id: str,
        label: str,
        constitution_path: str,
        content: str,
        actor: str,
    ) -> UUID:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        version_id = await self._conn.fetchval(
            """
            INSERT INTO theeyebeta.admin_agent_versions
              (agent_id, label, constitution_path, content_hash, created_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            agent_id,
            label,
            constitution_path,
            content_hash,
            actor,
        )
        return UUID(str(version_id))

    async def get_agent_version(self, agent_id: str, version_id: UUID) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            """
            SELECT id, agent_id, label, constitution_path, content_hash, created_at, created_by
              FROM theeyebeta.admin_agent_versions
             WHERE agent_id = $1 AND id = $2
            """,
            agent_id,
            version_id,
        )
        return dict(row) if row else None

    async def proposal_row(self, proposal_id: UUID) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            "SELECT id, status FROM theeyebeta.proposals WHERE id = $1",
            proposal_id,
        )

    async def defer_proposal(self, proposal_id: UUID, *, actor: str, note: str) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            UPDATE theeyebeta.proposals
               SET status = 'deferred',
                   reviewed_by = $2,
                   reviewed_at = now(),
                   review_notes = $3
             WHERE id = $1 AND status = 'pending'
            RETURNING id, status, reviewed_by, reviewed_at, review_notes
            """,
            proposal_id,
            actor,
            note,
        )

    async def supersede_proposal(self, proposal_id: UUID, *, actor: str, note: str) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            UPDATE theeyebeta.proposals
               SET status = 'superseded',
                   reviewed_by = $2,
                   reviewed_at = now(),
                   review_notes = $3
             WHERE id = $1 AND status IN ('pending', 'deferred')
            RETURNING id, status, reviewed_by, reviewed_at, review_notes
            """,
            proposal_id,
            actor,
            note,
        )

    async def rollback_proposal(self, proposal_id: UUID, *, actor: str, note: str) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            UPDATE theeyebeta.proposals
               SET status = 'pending',
                   reviewed_by = $2,
                   reviewed_at = now(),
                   review_notes = $3,
                   validation_backtest_id = NULL,
                   applied_at = NULL,
                   applied_commit_sha = NULL
             WHERE id = $1 AND status IN ('approved', 'applied', 'rejected', 'deferred')
            RETURNING id, status, reviewed_by, reviewed_at, review_notes
            """,
            proposal_id,
            actor,
            note,
        )

    async def backtest_row(self, backtest_id: UUID) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            SELECT id, strategy_id, start_date, end_date, universe, git_sha,
                   started_at, ended_at, status, result_blob_uri
              FROM theeyebeta.backtest_runs WHERE id = $1
            """,
            backtest_id,
        )

    async def cancel_backtest(self, backtest_id: UUID) -> asyncpg.Record | None:
        return await self._conn.fetchrow(
            """
            UPDATE theeyebeta.backtest_runs
               SET status = 'cancelled', ended_at = now()
             WHERE id = $1 AND status = 'running'
            RETURNING id, status, started_at, ended_at
            """,
            backtest_id,
        )

    async def list_briefings(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not await self._briefings_available():
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, title, status, generated_at, stale_after, blob_uri, export_uri, summary
              FROM theeyebeta.admin_briefings
             ORDER BY generated_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def briefing_row(self, briefing_id: UUID) -> dict[str, Any] | None:
        if not await self._briefings_available():
            return None
        row = await self._conn.fetchrow(
            """
            SELECT id, title, status, generated_at, stale_after, blob_uri, export_uri, summary
              FROM theeyebeta.admin_briefings WHERE id = $1
            """,
            briefing_id,
        )
        return dict(row) if row else None

    async def regenerate_briefing(self, *, title: str, actor: str) -> UUID:
        if not await self._briefings_available():
            msg = "admin_briefings table is not available; run the admin intelligence migration first"
            raise RuntimeError(msg)
        briefing_id = await self._conn.fetchval(
            """
            INSERT INTO theeyebeta.admin_briefings (title, status, summary)
            VALUES ($1, 'pending', $2)
            RETURNING id
            """,
            title,
            f"Queued by {actor}",
        )
        return UUID(str(briefing_id))

    async def mark_briefings_stale(self) -> int:
        if not await self._briefings_available():
            return 0
        val = await self._conn.fetchval(
            """
            WITH updated AS (
              UPDATE theeyebeta.admin_briefings
                 SET status = 'stale'
               WHERE status = 'ready'
                 AND stale_after IS NOT NULL
                 AND stale_after < now()
              RETURNING 1
            )
            SELECT COUNT(*)::int FROM updated
            """,
        )
        return int(val or 0)

    async def list_budgets(self) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT id, scope, monthly_limit_usd, warn_threshold_pct, updated_at, updated_by
              FROM theeyebeta.admin_cost_budgets
             ORDER BY scope
            """,
        )
        return [dict(row) for row in rows]

    async def patch_budget(
        self,
        scope: str,
        *,
        monthly_limit_usd: Decimal,
        warn_threshold_pct: Decimal,
        actor: str,
    ) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_cost_budgets
               SET monthly_limit_usd = $2,
                   warn_threshold_pct = $3,
                   updated_by = $4,
                   updated_at = now()
             WHERE scope = $1
            RETURNING id, scope, monthly_limit_usd, warn_threshold_pct, updated_at, updated_by
            """,
            scope,
            monthly_limit_usd,
            warn_threshold_pct,
            actor,
        )
        return dict(row) if row else None

    async def cost_state(self) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            SELECT kill_switch_active, kill_switch_reason, kill_switch_by, kill_switch_at, updated_at
              FROM theeyebeta.admin_cost_state WHERE id = 1
            """,
        )
        return dict(row) if row else {"kill_switch_active": False}

    async def set_kill_switch(self, *, active: bool, reason: str, actor: str) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_cost_state
               SET kill_switch_active = $1,
                   kill_switch_reason = $2,
                   kill_switch_by = $3,
                   kill_switch_at = CASE WHEN $1 THEN now() ELSE NULL END,
                   updated_at = now()
             WHERE id = 1
            RETURNING kill_switch_active, kill_switch_reason, kill_switch_by, kill_switch_at, updated_at
            """,
            active,
            reason,
            actor,
        )
        assert row is not None
        return dict(row)

    async def record_event(
        self,
        *,
        event_type: str,
        actor: str,
        reason: str | None,
        payload: dict[str, Any],
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO theeyebeta.admin_intelligence_events (event_type, actor, reason, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            actor,
            reason,
            json.dumps(payload, default=str),
        )
