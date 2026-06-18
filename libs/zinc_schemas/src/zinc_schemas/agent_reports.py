"""Persist and query operator-facing agent reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zinc_schemas.agent_hierarchy import OPERATOR_AUDIENCE

ReportType = str  # briefing | escalation | rollup | trade_synthesis
ReportStatus = str  # draft | published | superseded


class ReportConnection(Protocol):
    """Async DB connection shape used by report queries."""

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        """Fetch one row."""

    async def fetch(self, query: str, *args: object) -> list[Mapping[str, object]]:
        """Fetch multiple rows."""


class AgentReportRow(BaseModel):
    """One row from ``theeyebeta.agent_reports``."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: str
    audience: str
    run_id: UUID | None = None
    report_type: ReportType
    period_start: datetime | None = None
    period_end: datetime | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ReportStatus
    created_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def _coerce_payload(cls, value: object) -> dict[str, Any]:
        """asyncpg may return jsonb as str depending on driver settings."""
        if isinstance(value, str):
            return cast("dict[str, Any]", json.loads(value))
        if isinstance(value, dict):
            return cast("dict[str, Any]", value)
        return {}


class AgentReportCreate(BaseModel):
    """Input for inserting a new agent report."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    audience: str = OPERATOR_AUDIENCE
    run_id: UUID | None = None
    report_type: ReportType = "briefing"
    period_start: datetime | None = None
    period_end: datetime | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ReportStatus = "published"


def build_report_summary(run_body: dict[str, Any]) -> str:
    """Derive a one-line operator summary from an agent-runtime response."""
    briefing = run_body.get("briefing")
    if isinstance(briefing, dict):
        for key in (
            "summary",
            "rationale",
            "verdict",
            "outcome",
            "decision",
            "thesis",
            "counter_thesis",
            "market_stance",
        ):
            value = briefing.get(key)
            if value:
                return str(value)[:500]

    stance = str(run_body.get("market_stance") or "").strip()
    regime = str(run_body.get("regime_call") or "").strip()
    parts = [p for p in (stance, regime) if p]
    if parts:
        return " — ".join(parts)
    rows = run_body.get("decision_rows") or []
    if rows:
        first = rows[0]
        return (
            f"{first.get('decision', 'HOLD')} {first.get('instrument_symbol', '')}: "
            f"{str(first.get('rationale', ''))[:200]}"
        ).strip()
    return "Agent run completed with no structured summary."


async def insert_agent_report(conn: ReportConnection, report: AgentReportCreate) -> UUID:
    """Insert one report row; returns new id."""
    row = await conn.fetchrow(
        """
        INSERT INTO theeyebeta.agent_reports (
            agent_id, audience, run_id, report_type,
            period_start, period_end, summary, payload, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
        RETURNING id
        """,
        report.agent_id,
        report.audience,
        report.run_id,
        report.report_type,
        report.period_start,
        report.period_end,
        report.summary,
        json.dumps(report.payload),
        report.status,
    )
    if row is None:
        msg = "agent report insert did not return an id"
        raise RuntimeError(msg)
    return cast(UUID, row["id"])


async def fetch_operator_briefings(
    conn: ReportConnection,
    *,
    limit: int = 50,
    audience: str = OPERATOR_AUDIENCE,
) -> list[AgentReportRow]:
    """Return newest reports addressed to the operator."""
    rows = await conn.fetch(
        """
        SELECT id, agent_id, audience, run_id, report_type,
               period_start, period_end, summary, payload, status, created_at
          FROM theeyebeta.agent_reports
         WHERE audience = $1
           AND status = 'published'
         ORDER BY created_at DESC
         LIMIT $2
        """,
        audience,
        limit,
    )
    return [AgentReportRow.model_validate(dict(row)) for row in rows]


async def fetch_reports_for_parent(
    conn: ReportConnection,
    parent_id: str,
    *,
    since: datetime | None = None,
) -> list[AgentReportRow]:
    """Return child reports addressed to ``parent_id`` (for rollup input)."""
    if since is None:
        since = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = await conn.fetch(
        """
        SELECT id, agent_id, audience, run_id, report_type,
               period_start, period_end, summary, payload, status, created_at
          FROM theeyebeta.agent_reports
         WHERE audience = $1
           AND status = 'published'
           AND created_at >= $2
         ORDER BY created_at ASC
        """,
        parent_id,
        since,
    )
    return [AgentReportRow.model_validate(dict(row)) for row in rows]
