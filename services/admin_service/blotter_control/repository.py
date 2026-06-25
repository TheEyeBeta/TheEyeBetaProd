"""Blotter database reads and writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from blotter_control.registry import CANCELLABLE_STATUSES, LIVE_STATUSES, REPLACEABLE_STATUSES, STALE_POSITIONS_HOURS
from db_compat import column_exists, table_exists


class BlotterRepository:
    """Orders, executions, positions, accounts, blotter events."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=UTC)

    async def _order_metadata_sql(self) -> str:
        if await column_exists(self._conn, "theeyebeta", "orders", "metadata"):
            return "o.metadata"
        return "NULL::jsonb AS metadata"

    async def list_orders(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        metadata_sql = await self._order_metadata_sql()
        if status:
            rows = await self._conn.fetch(
                f"""
                SELECT o.id, o.client_order_id, o.broker_order_id, o.portfolio_id,
                       o.side, o.order_type, o.qty, o.limit_price, o.status,
                       o.filled_qty, o.avg_fill_price, {metadata_sql},
                       o.approved_by, o.approved_at, o.created_at, o.updated_at,
                       i.id AS instrument_id, i.symbol AS instrument_symbol,
                       e.code AS exchange_code
                  FROM theeyebeta.orders o
                  JOIN theeyebeta.instruments i ON i.id = o.instrument_id
                  LEFT JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                 WHERE o.status = $1
                 ORDER BY o.created_at DESC
                 LIMIT $2
                """,
                status,
                limit,
            )
        else:
            rows = await self._conn.fetch(
                f"""
                SELECT o.id, o.client_order_id, o.broker_order_id, o.portfolio_id,
                       o.side, o.order_type, o.qty, o.limit_price, o.status,
                       o.filled_qty, o.avg_fill_price, {metadata_sql},
                       o.approved_by, o.approved_at, o.created_at, o.updated_at,
                       i.id AS instrument_id, i.symbol AS instrument_symbol,
                       e.code AS exchange_code
                  FROM theeyebeta.orders o
                  JOIN theeyebeta.instruments i ON i.id = o.instrument_id
                  LEFT JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                 ORDER BY o.created_at DESC
                 LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def fetch_order(self, order_id: UUID) -> dict[str, Any] | None:
        metadata_sql = await self._order_metadata_sql()
        row = await self._conn.fetchrow(
            f"""
            SELECT o.id, o.client_order_id, o.broker_order_id, o.portfolio_id,
                   o.side, o.order_type, o.qty, o.limit_price, o.stop_price,
                   o.time_in_force, o.status, o.filled_qty, o.avg_fill_price,
                   {metadata_sql}, o.approved_by, o.approved_at, o.submitted_at,
                   o.created_at, o.updated_at,
                   i.id AS instrument_id, i.symbol AS instrument_symbol,
                   e.code AS exchange_code
              FROM theeyebeta.orders o
              JOIN theeyebeta.instruments i ON i.id = o.instrument_id
              LEFT JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
             WHERE o.id = $1
            """,
            order_id,
        )
        return dict(row) if row else None

    async def order_events(self, order_id: UUID) -> list[dict[str, Any]]:
        audit_rows = await self._conn.fetch(
            """
            SELECT id, actor, action, payload, created_at
              FROM theeyebeta.audit_log
             WHERE entity_type = 'order'
               AND entity_id = $1
             ORDER BY created_at ASC
            """,
            str(order_id),
        )
        events: list[dict[str, Any]] = []
        for row in audit_rows:
            payload = row["payload"] or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            events.append(
                {
                    "source": "audit",
                    "event_type": row["action"],
                    "actor": row["actor"],
                    "payload": payload if isinstance(payload, dict) else {},
                    "ts": row["created_at"],
                },
            )
        exec_rows = await self._conn.fetch(
            """
            SELECT id, ts, qty, price, commission, raw
              FROM theeyebeta.executions
             WHERE order_id = $1
             ORDER BY ts ASC
            """,
            order_id,
        )
        for row in exec_rows:
            events.append(
                {
                    "source": "execution",
                    "event_type": "fill",
                    "actor": "broker",
                    "payload": {
                        "qty": float(row["qty"]),
                        "price": float(row["price"]),
                        "commission": float(row["commission"]),
                    },
                    "ts": row["ts"],
                },
            )
        events.sort(key=lambda item: item["ts"])
        return events

    async def cancel_order(self, order_id: UUID, *, actor: str, reason: str) -> dict[str, Any]:
        row = await self._conn.fetchrow(
            """
            UPDATE theeyebeta.orders
               SET status = 'cancelled',
                   metadata = COALESCE(metadata, '{}'::jsonb)
                       || jsonb_build_object('cancel_reason', $1::text, 'cancelled_by', $2::text),
                   updated_at = now()
             WHERE id = $3
               AND status = ANY($4::text[])
             RETURNING id, status, metadata, updated_at
            """,
            reason,
            actor,
            order_id,
            list(CANCELLABLE_STATUSES),
        )
        return dict(row) if row else {}

    async def replace_order(
        self,
        order_id: UUID,
        *,
        actor: str,
        reason: str,
        qty: float | None,
        limit_price: float | None,
    ) -> dict[str, Any]:
        sets: list[str] = ["updated_at = now()"]
        args: list[Any] = [reason, actor, order_id, list(REPLACEABLE_STATUSES)]
        if qty is not None:
            sets.append(f"qty = ${len(args) + 1}")
            args.append(qty)
        if limit_price is not None:
            sets.append(f"limit_price = ${len(args) + 1}")
            args.append(limit_price)
        sets.append(
            "metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object("
            "'replace_reason', $1::text, 'replaced_by', $2::text)",
        )
        row = await self._conn.fetchrow(
            f"""
            UPDATE theeyebeta.orders
               SET {", ".join(sets)}
             WHERE id = $3
               AND status = ANY($4::text[])
             RETURNING id, status, qty, limit_price, metadata, updated_at
            """,
            *args,
        )
        return dict(row) if row else {}

    async def list_executions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT e.id, e.order_id, e.ts, e.qty, e.price, e.commission,
                   o.client_order_id, i.symbol
              FROM theeyebeta.executions e
              JOIN theeyebeta.orders o ON o.id = e.order_id
              JOIN theeyebeta.instruments i ON i.id = o.instrument_id
             ORDER BY e.ts DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_positions(self, *, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        if portfolio_id:
            rows = await self._conn.fetch(
                """
                SELECT p.id, p.portfolio_id, p.qty, p.avg_entry_price,
                       p.market_value, p.unrealized_pnl, p.updated_at,
                       i.symbol
                  FROM theeyebeta.positions p
                  JOIN theeyebeta.instruments i ON i.id = p.instrument_id
                 WHERE p.portfolio_id = $1::uuid
                 ORDER BY i.symbol ASC
                """,
                UUID(portfolio_id),
            )
        else:
            rows = await self._conn.fetch(
                """
                SELECT p.id, p.portfolio_id, p.qty, p.avg_entry_price,
                       p.market_value, p.unrealized_pnl, p.updated_at,
                       i.symbol
                  FROM theeyebeta.positions p
                  JOIN theeyebeta.instruments i ON i.id = p.instrument_id
                 ORDER BY p.updated_at DESC
                """,
            )
        return [dict(row) for row in rows]

    async def local_positions_for_recon(self) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT i.symbol, p.qty
              FROM theeyebeta.positions p
              JOIN theeyebeta.instruments i ON i.id = p.instrument_id
            """,
        )
        return [{"symbol": str(row["symbol"]), "qty": float(row["qty"])} for row in rows]

    async def local_active_orders_for_recon(self) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT client_order_id, broker_order_id, status, filled_qty
              FROM theeyebeta.orders
             WHERE status = ANY($1::text[])
            """,
            list(LIVE_STATUSES),
        )
        return [
            {
                "client_order_id": str(row["client_order_id"]),
                "broker_order_id": str(row["broker_order_id"] or ""),
                "status": str(row["status"]),
                "filled_qty": float(row["filled_qty"]),
            }
            for row in rows
        ]

    async def default_portfolio_id(self) -> str | None:
        row = await self._conn.fetchval(
            "SELECT id::text FROM theeyebeta.portfolios ORDER BY created_at ASC NULLS LAST LIMIT 1",
        )
        return str(row) if row else None

    async def account_summary(self, *, portfolio_id: str | None = None) -> dict[str, Any]:
        pid = portfolio_id or await self.default_portfolio_id()
        if pid is None:
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT a.id, a.external_id, a.broker, a.mode, a.base_currency, a.status,
                   p.id AS portfolio_id, p.name AS portfolio_name
              FROM theeyebeta.portfolios p
              JOIN theeyebeta.accounts a ON a.id = p.account_id
             WHERE p.id = $1::uuid
            """,
            UUID(pid),
        )
        return dict(row) if row else {}

    async def positions_stale(self) -> bool:
        row = await self._conn.fetchval(
            "SELECT MAX(updated_at) FROM theeyebeta.positions",
        )
        if row is None:
            return True
        ts = row if row.tzinfo else row.replace(tzinfo=UTC)
        return self.utc_now() - ts > timedelta(hours=STALE_POSITIONS_HOURS)

    async def get_state(self) -> dict[str, Any]:
        if not await table_exists(self._conn, "theeyebeta", "admin_blotter_state"):
            return {}
        row = await self._conn.fetchrow(
            """
            SELECT last_broker_test_at, last_broker_test_by, last_broker_test_ok,
                   last_reconciliation_at, last_reconciliation_by, last_drift_count, updated_at
              FROM theeyebeta.admin_blotter_state
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
            UPDATE theeyebeta.admin_blotter_state
               SET {sets}, updated_at = now()
             WHERE id = 1
            RETURNING last_broker_test_at, last_broker_test_by, last_broker_test_ok,
                      last_reconciliation_at, last_reconciliation_by, last_drift_count, updated_at
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
        await self._conn.execute(
            """
            INSERT INTO theeyebeta.admin_blotter_events (event_type, actor, reason, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            actor,
            reason,
            json.dumps(payload, default=str),
        )

    async def list_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT id, event_type, actor, reason, payload, created_at
              FROM theeyebeta.admin_blotter_events
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]
