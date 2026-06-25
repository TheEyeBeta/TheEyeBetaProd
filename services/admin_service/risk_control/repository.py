"""Risk cockpit database reads and writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from db_compat import table_exists
from risk_control.registry import DEFAULT_LIMITS, STALE_METRICS_HOURS


class RiskRepository:
    """Risk metrics, limits, overrides, and events."""

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

    async def get_limits_row(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_risk_limits"):
            return {"version": 1, "limits": DEFAULT_LIMITS, "updated_at": None, "updated_by": None}
        row = await self._conn.fetchrow(
            """
            SELECT version, limits, updated_at, updated_by
              FROM theeyebeta.admin_risk_limits
             WHERE id = 1
            """,
        )
        if row is None:
            return {"version": 1, "limits": DEFAULT_LIMITS, "updated_at": None, "updated_by": None}
        limits = row["limits"]
        if isinstance(limits, str):
            limits = json.loads(limits)
        return {
            "version": int(row["version"]),
            "limits": {**DEFAULT_LIMITS, **(limits or {})},
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    async def patch_limits(self, limits: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        current = await self.get_limits_row()
        merged = {**current["limits"], **limits}
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.admin_risk_limits
               SET limits = $1::jsonb,
                   version = version + 1,
                   updated_at = now(),
                   updated_by = $2
             WHERE id = 1
            RETURNING version, limits, updated_at, updated_by
            """,
            json.dumps(merged),
            updated_by,
        )
        assert row is not None
        return {
            "version": int(row["version"]),
            "limits": dict(row["limits"]),
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    async def get_state(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_risk_state"):
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT trading_locked, lock_reason, locked_by, locked_at,
                   last_compute_at, last_compute_by, last_compute_portfolio_id, updated_at
              FROM theeyebeta.admin_risk_state
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
            UPDATE theeyebeta.admin_risk_state
               SET {sets}, updated_at = now()
             WHERE id = 1
            RETURNING trading_locked, lock_reason, locked_by, locked_at,
                      last_compute_at, last_compute_by, last_compute_portfolio_id, updated_at
            """,
            *fields.values(),
        )
        assert row is not None
        return dict(row)

    async def latest_metrics(self, portfolio_id: str) -> dict[str, Any] | None:
        if not await table_exists(self._conn, "theeyebeta", "risk_metrics"):
            return None
        row = await self._conn.fetchrow(
            """
            SELECT portfolio_id, ts, var_95, cvar_95, max_drawdown,
                   gross_exposure, net_exposure, beta_spy, concentration_hhi, raw
              FROM theeyebeta.risk_metrics
             WHERE portfolio_id = $1::uuid
             ORDER BY ts DESC
             LIMIT 1
            """,
            UUID(portfolio_id),
        )
        return dict(row) if row else None

    async def portfolio_mandate(self, portfolio_id: str) -> dict[str, Any]:
        row = await self._conn.fetchval(
            "SELECT mandate FROM theeyebeta.portfolios WHERE id = $1::uuid",
            UUID(portfolio_id),
        )
        if row is None:
            return DEFAULT_LIMITS.copy()
        mandate = row if isinstance(row, dict) else json.loads(row or "{}")
        return {**DEFAULT_LIMITS, **mandate}

    async def list_breaches(self, portfolio_id: str, limits: dict[str, float]) -> list[dict[str, Any]]:
        metrics = await self.latest_metrics(portfolio_id)
        if metrics is None:
            return []
        nav = max(float(metrics.get("gross_exposure") or 1), 1.0)
        breaches: list[dict[str, Any]] = []
        var_frac = float(metrics.get("var_95") or 0)
        if var_frac > limits.get("max_var", DEFAULT_LIMITS["max_var"]):
            breaches.append(
                {
                    "check": "portfolio_var_95",
                    "limit": limits["max_var"],
                    "actual": var_frac,
                    "severity": "critical",
                },
            )
        hhi = float(metrics.get("concentration_hhi") or 0)
        if hhi > limits.get("max_hhi", DEFAULT_LIMITS["max_hhi"]):
            breaches.append(
                {
                    "check": "concentration_hhi",
                    "limit": limits["max_hhi"],
                    "actual": hhi,
                    "severity": "warn",
                },
            )
        dd = float(metrics.get("max_drawdown") or 0)
        if dd > limits.get("max_drawdown_pct", DEFAULT_LIMITS["max_drawdown_pct"]):
            breaches.append(
                {
                    "check": "drawdown_circuit_breaker",
                    "limit": limits["max_drawdown_pct"],
                    "actual": dd,
                    "severity": "critical",
                },
            )
        raw = metrics.get("raw") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        cluster = (raw or {}).get("cluster_exposures") or {}
        max_cluster = max(cluster.values(), default=0.0)
        if float(max_cluster) > limits.get("max_correlation_cluster_pct", 0.40):
            breaches.append(
                {
                    "check": "correlation_cluster_exposure",
                    "limit": limits["max_correlation_cluster_pct"],
                    "actual": float(max_cluster),
                    "severity": "warn",
                },
            )
        return breaches

    async def list_failures(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "risk_metrics"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT portfolio_id, ts, raw
              FROM theeyebeta.risk_metrics
             WHERE raw->'validation'->>'outcome' = 'BLOCK'
             ORDER BY ts DESC
             LIMIT $1
            """,
            limit,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            raw = row["raw"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            validation = (raw or {}).get("validation") or {}
            out.append(
                {
                    "portfolio_id": str(row["portfolio_id"]),
                    "ts": row["ts"],
                    "failed_checks": validation.get("failed_checks") or [],
                    "outcome": validation.get("outcome"),
                },
            )
        return out

    async def metrics_stale(self, portfolio_id: str) -> bool:
        metrics = await self.latest_metrics(portfolio_id)
        if metrics is None:
            return True
        ts = metrics["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return self.utc_now() - ts > timedelta(hours=STALE_METRICS_HOURS)

    async def insert_override(
        self,
        *,
        portfolio_id: str | None,
        check_name: str,
        reason: str,
        actor: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            INSERT INTO theeyebeta.admin_risk_overrides
                (portfolio_id, check_name, reason, actor, expires_at)
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id, portfolio_id, check_name, reason, actor, expires_at, active, created_at
            """,
            UUID(portfolio_id) if portfolio_id else None,
            check_name,
            reason,
            actor,
            expires_at,
        )
        assert row is not None
        return dict(row)

    async def list_overrides(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        if not await table_exists(self._conn, "theeyebeta", "admin_risk_overrides"):
            return []
        clause = "WHERE active AND (expires_at IS NULL OR expires_at > now())" if active_only else ""
        rows = await self._conn.fetch(
            f"""
            SELECT id, portfolio_id, check_name, reason, actor, expires_at, active, created_at
              FROM theeyebeta.admin_risk_overrides
              {clause}
             ORDER BY created_at DESC
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
            INSERT INTO theeyebeta.admin_risk_events
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
        if not await table_exists(self._conn, "theeyebeta", "admin_risk_events"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_risk_events
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def trading_halt_state(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_trading_state"):
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT emergency_halt, live_trading_enabled, last_halt_reason, last_operator
              FROM theeyebeta.admin_trading_state
             WHERE id = 1
            """,
        )
        return dict(row) if row else {}
