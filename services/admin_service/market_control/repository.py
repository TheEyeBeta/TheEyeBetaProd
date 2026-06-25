"""Market data database reads and writes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from db_compat import max_date_column, table_exists
from market_control.registry import STALE_DATASET_DAYS


class MarketRepository:
    """Gaps, freshness, universe, snapshots, and admin events."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def _table_exists(self, schema: str, name: str) -> bool:
        return bool(
            await self._conn.fetchval(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.tables
                   WHERE table_schema = $1 AND table_name = $2
                )
                """,
                schema,
                name,
            ),
        )

    async def list_gaps(self, *, limit: int = 50, open_only: bool = True) -> list[dict[str, Any]]:
        if not await self._table_exists("public", "audit_data_gaps"):
            return []
        clause = "WHERE remediation_state = 'OPEN'" if open_only else ""
        try:
            rows = await self._conn.fetch(
                f"""
                SELECT gap_id, dataset_type, trade_date, severity, remediation_state,
                       remediation_notes, expected_count, actual_count, updated_at
                  FROM public.audit_data_gaps
                  {clause}
                 ORDER BY severity DESC, trade_date DESC
                 LIMIT $1
                """,
                limit,
            )
        except asyncpg.PostgresError:
            return []
        return [dict(row) for row in rows]

    async def gap_counts(self) -> dict[str, int]:
        if not await self._table_exists("public", "audit_data_gaps"):
            return {"open_total": 0, "price_open": 0, "macro_open": 0}
        try:
            row = await self._conn.fetchrow(
                """
                SELECT COUNT(*) FILTER (WHERE remediation_state = 'OPEN') AS open_total,
                       COUNT(*) FILTER (
                         WHERE remediation_state = 'OPEN'
                           AND dataset_type IN ('price_daily', 'prices_daily')
                       ) AS price_open,
                       COUNT(*) FILTER (
                         WHERE remediation_state = 'OPEN'
                           AND dataset_type ILIKE '%macro%'
                       ) AS macro_open
                  FROM public.audit_data_gaps
                """,
            )
        except asyncpg.PostgresError:
            return {"open_total": 0, "price_open": 0, "macro_open": 0}
        return {
            "open_total": int(row["open_total"] or 0),
            "price_open": int(row["price_open"] or 0),
            "macro_open": int(row["macro_open"] or 0),
        }

    async def resolve_gap(self, gap_id: int, *, note: str, actor: str) -> dict[str, Any] | None:
        if not await self._table_exists("public", "audit_data_gaps"):
            return None
        row = await self._conn.fetchrow(
            """
            UPDATE public.audit_data_gaps
               SET remediation_state = 'RESOLVED',
                   remediation_notes = COALESCE(remediation_notes, '') || ' | ' || $2,
                   updated_at = now()
             WHERE gap_id = $1
               AND remediation_state = 'OPEN'
            RETURNING gap_id, dataset_type, trade_date, severity, remediation_state, remediation_notes
            """,
            gap_id,
            f"[admin:{actor}] {note}",
        )
        return dict(row) if row else None

    async def universe_stats(self) -> dict[str, Any]:
        active = await self._conn.fetchval(
            "SELECT COUNT(*)::int FROM theeyebeta.instruments WHERE active",
        )
        exchanges = await self._conn.fetchval("SELECT COUNT(*)::int FROM theeyebeta.exchanges")
        return {
            "active_instruments": int(active or 0),
            "exchange_count": int(exchanges or 0),
        }

    async def dataset_freshness(self) -> list[dict[str, Any]]:
        datasets: list[dict[str, Any]] = []
        if await self._table_exists("theeyebeta", "prices_daily"):
            latest = await max_date_column(
                self._conn,
                schema="theeyebeta",
                table="prices_daily",
            )
            datasets.append(self._freshness_row("prices_daily", latest))
        elif await self._table_exists("public", "price_daily"):
            latest = await max_date_column(
                self._conn,
                schema="public",
                table="price_daily",
                candidates=("date", "trade_date"),
            )
            datasets.append(self._freshness_row("price_daily", latest))
        if await self._table_exists("theeyebeta", "macro_indicators"):
            latest = await max_date_column(
                self._conn,
                schema="theeyebeta",
                table="macro_indicators",
                candidates=("as_of_date", "date", "trade_date"),
            )
            datasets.append(self._freshness_row("macro_indicators", latest))
        if await self._table_exists("theeyebeta", "fundamentals"):
            latest = await max_date_column(
                self._conn,
                schema="theeyebeta",
                table="fundamentals",
                candidates=("period_end", "as_of_date", "date"),
            )
            datasets.append(self._freshness_row("fundamentals", latest))
        if await self._table_exists("theeyebeta", "news_articles"):
            latest = await max_date_column(
                self._conn,
                schema="theeyebeta",
                table="news_articles",
                candidates=("published_at", "date"),
            )
            datasets.append(self._freshness_row("news_articles", latest))
        return datasets

    @staticmethod
    def _freshness_row(dataset: str, latest: date | datetime | None) -> dict[str, Any]:
        stale = True
        if latest is not None:
            if isinstance(latest, datetime):
                latest = latest.date()
            stale = date.today() - latest > timedelta(days=STALE_DATASET_DAYS)
        return {
            "dataset": dataset,
            "latest_date": latest.isoformat() if latest else None,
            "stale": stale,
        }

    async def market_cap_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not await self._table_exists("theeyebeta", "corporate_actions"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT ca.id, ca.action_type, ca.ex_date, ca.cash_amount AS amount, i.symbol
              FROM theeyebeta.corporate_actions ca
              JOIN theeyebeta.instruments i ON i.id = ca.instrument_id
             WHERE ca.action_type ILIKE '%split%'
                OR ca.action_type ILIKE '%dividend%'
             ORDER BY ca.ex_date DESC NULLS LAST
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_snapshots(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not await self._table_exists("theeyebeta", "data_snapshots_packaged"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, snapshot_id, market, trade_date, schema_version,
                   blob_uri, universe_size, packaged_at
              FROM theeyebeta.data_snapshots_packaged
             ORDER BY trade_date DESC, packaged_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_snapshot(self, snapshot_id: UUID) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            """
            SELECT id, snapshot_id, market, trade_date, schema_version,
                   blob_uri, encode(blob_sha256, 'hex') AS blob_sha256,
                   universe_size, packaged_at, packager_git_sha
              FROM theeyebeta.data_snapshots_packaged
             WHERE id = $1::uuid OR snapshot_id = $1::uuid
             LIMIT 1
            """,
            snapshot_id,
        )
        return dict(row) if row else None

    async def snapshot_artifacts(self, snapshot_id: UUID) -> list[dict[str, Any]]:
        row = await self.get_snapshot(snapshot_id)
        if row is None:
            return []
        return [
            {
                "kind": "packaged_blob",
                "uri": row["blob_uri"],
                "sha256": row.get("blob_sha256"),
                "universe_size": row["universe_size"],
            },
        ]

    async def worker_run_summary(self) -> list[dict[str, Any]]:
        if not await self._table_exists("public", "audit_worker_runs"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT worker_name,
                   MAX(started_at) FILTER (WHERE status = 'COMPLETED') AS last_success,
                   MAX(started_at) FILTER (WHERE status = 'FAILED') AS last_failure
              FROM public.audit_worker_runs
             GROUP BY worker_name
             ORDER BY worker_name
            """,
        )
        return [dict(row) for row in rows]

    async def get_state(self) -> dict[str, Any]:
        if not await self._table_exists("theeyebeta", "admin_market_state"):
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT last_backfill_at, last_backfill_by,
                   last_snapshot_build_at, last_snapshot_build_by, updated_at
              FROM theeyebeta.admin_market_state
             WHERE id = 1
            """,
        )
        return dict(row) if row else {}

    async def save_state(self, **fields: Any) -> dict[str, Any]:
        if not fields:
            return await self.get_state()
        if not await self._table_exists("theeyebeta", "admin_market_state"):
            return {}
        sets = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(fields, start=1))
        row = await self._conn.fetchrow(
            f"""
            UPDATE theeyebeta.admin_market_state
               SET {sets}, updated_at = now()
             WHERE id = 1
            RETURNING last_backfill_at, last_backfill_by,
                      last_snapshot_build_at, last_snapshot_build_by, updated_at
            """,
            *fields.values(),
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
        if not await self._table_exists("theeyebeta", "admin_market_events"):
            return
        await self._conn.execute(
            """
            INSERT INTO theeyebeta.admin_market_events (event_type, actor, reason, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            actor,
            reason,
            json.dumps(payload, default=str),
        )

    async def list_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not await self._table_exists("theeyebeta", "admin_market_events"):
            return []
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_market_events
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]
