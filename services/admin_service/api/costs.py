"""Admin costs API — daily aggregates + per-agent monthly rollups."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import asyncpg
import structlog
from auth import CurrentUser
from deps import DbConn
from fastapi import APIRouter, HTTPException, Query, status

from zinc_schemas.admin_dto import (
    AgentCostEntry,
    CostsByAgentResponse,
    DailyCostEntry,
    DailyCostsResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/costs", tags=["costs"])

_DEFAULT_DAYS = 30
_MAX_DAYS = 365
_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _to_decimal(raw: object) -> Decimal:
    """Cast asyncpg numeric output (Decimal | None) to a non-null Decimal."""
    if raw is None:
        return Decimal("0")
    if isinstance(raw, Decimal):
        return raw
    return Decimal(str(raw))


def _parse_month(value: str) -> tuple[date, date]:
    """Validate ``YYYY-MM`` and return the half-open ``[start, end)`` window."""
    if not _MONTH_PATTERN.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="month must match YYYY-MM",
        )
    year = int(value[:4])
    month = int(value[5:7])
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def parse_month(value: str) -> tuple[date, date]:
    """Public wrapper around :func:`_parse_month` for the HTML view router."""
    return _parse_month(value)


def current_month_key(today: date | None = None) -> str:
    """Return ``today``'s month in ``YYYY-MM`` form (defaults to UTC today)."""
    today = today or date.today()  # noqa: DTZ011 — calendar boundary
    return f"{today.year:04d}-{today.month:02d}"


@dataclass(slots=True)
class VendorCostRow:
    """Month-to-date cost row aggregated by vendor across model + API sources."""

    vendor: str
    source: str
    cost_usd: Decimal


async def fetch_daily_costs(
    conn: asyncpg.Connection,
    days: int,
) -> DailyCostsResponse:
    """Return :class:`DailyCostsResponse` for the trailing ``days`` window."""
    if days < 1 or days > _MAX_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"days must be between 1 and {_MAX_DAYS}",
        )
    end_date = date.today()  # noqa: DTZ011 — calendar boundary
    start_date = end_date - timedelta(days=days - 1)

    rows: list[asyncpg.Record] = await conn.fetch(
        """
        WITH days AS (
            SELECT generate_series($1::date, $2::date, interval '1 day')::date AS d
        ),
        mr AS (
            SELECT created_at::date AS d, SUM(cost_usd) AS cost_usd
              FROM theeyebeta.model_runs
             WHERE created_at >= $1::timestamptz
               AND created_at < ($2::date + interval '1 day')::timestamptz
             GROUP BY created_at::date
        ),
        ac AS (
            SELECT ts AS d, SUM(cost_usd) AS cost_usd
              FROM theeyebeta.api_costs
             WHERE ts BETWEEN $1::date AND $2::date
             GROUP BY ts
        )
        SELECT
            days.d AS date,
            COALESCE(mr.cost_usd, 0) AS model_cost_usd,
            COALESCE(ac.cost_usd, 0) AS api_cost_usd,
            COALESCE(mr.cost_usd, 0) + COALESCE(ac.cost_usd, 0) AS total_cost_usd
          FROM days
          LEFT JOIN mr ON mr.d = days.d
          LEFT JOIN ac ON ac.d = days.d
         ORDER BY days.d DESC
        """,
        start_date,
        end_date,
    )

    entries = [
        DailyCostEntry(
            date=row["date"],
            model_cost_usd=_to_decimal(row["model_cost_usd"]),
            api_cost_usd=_to_decimal(row["api_cost_usd"]),
            total_cost_usd=_to_decimal(row["total_cost_usd"]),
        )
        for row in rows
    ]
    total = sum((e.total_cost_usd for e in entries), Decimal("0"))
    return DailyCostsResponse(
        days=days,
        start_date=start_date,
        end_date=end_date,
        entries=entries,
        total_cost_usd=total,
    )


async def fetch_costs_by_agent(
    conn: asyncpg.Connection,
    month: str,
) -> CostsByAgentResponse:
    """Return :class:`CostsByAgentResponse` for the calendar month ``YYYY-MM``."""
    start_date, end_date = _parse_month(month)
    rows: list[asyncpg.Record] = await conn.fetch(
        """
        SELECT
            ar.agent_id                              AS agent_id,
            COUNT(DISTINCT ar.id)::int               AS runs,
            COUNT(mr.id)::int                        AS model_runs,
            COALESCE(SUM(mr.input_tokens), 0)::int   AS input_tokens,
            COALESCE(SUM(mr.output_tokens), 0)::int  AS output_tokens,
            COALESCE(SUM(mr.cost_usd), 0)            AS cost_usd
          FROM theeyebeta.agent_runs ar
          JOIN theeyebeta.model_runs mr ON mr.run_id = ar.id
         WHERE mr.created_at >= $1::timestamptz
           AND mr.created_at <  $2::timestamptz
         GROUP BY ar.agent_id
         ORDER BY cost_usd DESC, ar.agent_id ASC
        """,
        start_date,
        end_date,
    )
    agents = [
        AgentCostEntry(
            agent_id=row["agent_id"],
            runs=int(row["runs"]),
            model_runs=int(row["model_runs"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cost_usd=_to_decimal(row["cost_usd"]),
        )
        for row in rows
    ]
    total = sum((a.cost_usd for a in agents), Decimal("0"))
    return CostsByAgentResponse(
        month=month,
        start_date=start_date,
        end_date=end_date - timedelta(days=1),
        agents=agents,
        total_cost_usd=total,
    )


async def fetch_costs_by_vendor(
    conn: asyncpg.Connection,
    month: str,
) -> list[VendorCostRow]:
    """Return the month-to-date cost broken down by vendor across both sources.

    ``model_runs.provider`` rows are tagged ``source='model'``, ``api_costs.vendor``
    rows are tagged ``source='api'``. Rows are ordered by cost desc.
    """
    start_date, end_date = _parse_month(month)
    rows = await conn.fetch(
        """
        WITH model AS (
            SELECT provider AS vendor,
                   'model'::text AS source,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd
              FROM theeyebeta.model_runs
             WHERE created_at >= $1::timestamptz
               AND created_at <  $2::timestamptz
             GROUP BY provider
        ),
        api AS (
            SELECT vendor,
                   'api'::text AS source,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd
              FROM theeyebeta.api_costs
             WHERE ts >= $1::date
               AND ts <  $2::date
             GROUP BY vendor
        )
        SELECT * FROM model
        UNION ALL
        SELECT * FROM api
        ORDER BY cost_usd DESC, vendor ASC
        """,
        start_date,
        end_date,
    )
    return [
        VendorCostRow(
            vendor=row["vendor"],
            source=row["source"],
            cost_usd=_to_decimal(row["cost_usd"]),
        )
        for row in rows
    ]


def register_costs_routes() -> APIRouter:
    """Attach cost read handlers (GET only — default rate limits apply)."""

    @router.get("/daily", response_model=DailyCostsResponse)
    async def get_daily_costs(
        user: CurrentUser,
        conn: DbConn,
        days: int = Query(default=_DEFAULT_DAYS, ge=1, le=_MAX_DAYS),
    ) -> DailyCostsResponse:
        """Aggregate LLM + vendor API costs across the last ``days`` days."""
        response = await fetch_daily_costs(conn, days)
        log.info(
            "admin_costs_daily",
            days=days,
            entry_count=len(response.entries),
            total_usd=str(response.total_cost_usd),
            sub=user["sub"],
        )
        return response

    @router.get("/by-agent", response_model=CostsByAgentResponse)
    async def get_costs_by_agent(
        user: CurrentUser,
        conn: DbConn,
        month: str = Query(..., description="Calendar month in YYYY-MM."),
    ) -> CostsByAgentResponse:
        """Aggregate ``model_runs`` cost per agent for one calendar month."""
        response = await fetch_costs_by_agent(conn, month)
        log.info(
            "admin_costs_by_agent",
            month=month,
            agent_count=len(response.agents),
            total_usd=str(response.total_cost_usd),
            sub=user["sub"],
        )
        return response

    return router
