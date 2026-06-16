"""Server-rendered admin pages (Jinja2 + htmx fragments).

These routes return ``HTMLResponse`` rather than JSON. They reuse the same
DB / external-service helpers as the JSON API routers (``api/orders.py``,
``api/audit.py``, ``api/backtest.py``) — calling those helpers in-process
avoids an HTTP self-loop and keeps the dashboard load to a single round-trip
of SQL queries.

Routes shipped here:

* ``GET  /admin/``                                     — full dashboard page.
* ``GET  /admin/fragments/stats``                      — 4 stat cards (htmx polling target).
* ``POST /admin/actions/verify-audit-chain``           — audit-service verify; refreshed audit card.
* ``POST /admin/actions/run-daily-backtest``           — backtest-engine trigger; flash toast.
* ``GET  /admin/orders``                             — pending orders table page.
* ``GET  /admin/orders/fragments/{id}/rationale``    — htmx-expandable rationale.
* ``GET  /admin/orders/fragments/{id}/reject-modal`` — reject reason modal (target ``#modal``).
* ``POST /admin/orders/fragments/{id}/approve``      — approve + return refreshed row HTML.
* ``POST /admin/orders/fragments/{id}/reject``       — reject + return refreshed row HTML.
* ``GET  /admin/audit``                              — audit log page (filter form + table).
* ``GET  /admin/audit/fragments/log``                — table fragment (filter + cursor pagination).
* ``GET  /admin/audit/fragments/verify``             — chain-verify result card for [from, to].
* ``GET  /admin/agents``                             — agents page (left list + right detail pane).
* ``GET  /admin/agents/fragments/{id}/runs``         — right pane "Recent runs" tab.
* ``GET  /admin/agents/fragments/{id}/constitution`` — right pane "Constitution" tab.
* ``GET  /admin/agents/fragments/{id}/run-modal``    — Run Now modal form.
* ``POST /admin/agents/fragments/{id}/run``          — submit Run Now, return flash + refreshed row.
* ``GET  /admin/violations``                         — guard violations page (filter form + table).
* ``GET  /admin/violations/fragments/list``          — table fragment (filter + cursor pagination).
* ``GET  /admin/violations/fragments/{id}/resolve-modal`` — resolve-note modal form.
* ``POST /admin/violations/fragments/{id}/resolve``  — submit resolve, return refreshed row.
* ``GET  /admin/costs``                       — costs page (bar + doughnut + MTD tables).
* ``GET  /admin/costs/fragments/daily``       — daily chart fragment (per ``days``).
* ``GET  /admin/costs/fragments/by-agent``    — doughnut + table fragment (per ``month``).
* ``GET  /admin/costs/fragments/vendor``      — MTD vendor table fragment (per ``month``).
* ``GET  /admin/sql``                         — SQL playground (CodeMirror editor + mode toggle).
* ``POST /admin/sql/fragments/query``         — run a SELECT; returns the result table partial.
* ``GET  /admin/sql/fragments/confirm``       — show the "I UNDERSTAND" modal for a write.
* ``POST /admin/sql/fragments/execute``       — run a write after confirmation; returns result card.
* ``GET  /admin/proposals``                       — proposals page (pending/approved/rejected tabs).
* ``GET  /admin/proposals/fragments/tab``         — swap the active tab's cards.
* ``GET  /admin/proposals/fragments/{id}/approve-modal`` — approve form (with backtest fields).
* ``POST /admin/proposals/fragments/{id}/approve``       — submit approve, returns refreshed card.
* ``GET  /admin/proposals/fragments/{id}/reject-modal``  — reject form (notes required).
* ``POST /admin/proposals/fragments/{id}/reject``        — submit reject, returns refreshed card.
* ``GET  /admin/proposals/fragments/{id}/backtest-status`` — poll validation backtest_run.

Content negotiation: ``GET /admin/agents`` returns JSON when ``Accept`` is
``application/json`` (or anything without ``text/html``) so that the existing
JSON API contract — verified by ``tests/test_agents.py`` — is preserved.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import asyncpg
import httpx
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, NatsClient, SettingsDep
from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from rbac import Role, require_role
from slowapi import Limiter
from web import page_context, templates

from api.agents import (
    fetch_agent_runs,
    fetch_agents_summary,
    read_agent_constitution,
    trigger_agent_run_impl,
)
from api.audit import call_audit_service_verify, fetch_audit_log_page
from api.costs import (
    current_month_key,
    fetch_costs_by_agent,
    fetch_costs_by_vendor,
    fetch_daily_costs,
    parse_month,
)
from api.guard import (
    VALID_SEVERITIES,
    fetch_guard_violation,
    fetch_guard_violations_page,
    resolve_guard_violation_impl,
    validate_severity,
)
from api.orders import (
    _SELECT_ORDER,
    _fetch_order,
    approve_pending_order,
    reject_pending_order,
)
from api.proposals import (
    PROPOSALS_DEFAULT_LIMIT,
    VALID_PROPOSAL_CATEGORIES,
    approve_proposal_impl,
    fetch_backtest_status,
    fetch_proposal_detail,
    fetch_proposals_page,
    reject_proposal_impl,
)
from api.sql import (
    QUERY_MAX_ROWS,
    QUERY_TIMEOUT_SECONDS,
    run_select_statement,
    run_write_statement,
)
from zinc_schemas.admin_dto import (
    AgentMessageDTO,
    AgentsListResponse,
    AgentSummary,
    ApproveProposalRequest,
    AuditLogEntry,
    AuditVerifyResponse,
    CostsByAgentResponse,
    DailyCostsResponse,
    ProposalDetail,
    ProposalSummary,
    RejectProposalRequest,
    RunAgentRequest,
)

log = structlog.get_logger()

router = APIRouter(tags=["views"], include_in_schema=False)

_BACKTEST_TIMEOUT_SECONDS = 60.0
_AUDIT_MAX_LIMIT = 500
_AUDIT_MIN_LIMIT = 1
_PAYLOAD_SNIPPET_CHARS = 160
_AGENT_RUNS_LIMIT = 50
_VIOLATIONS_DEFAULT_LIMIT = 50
_VIOLATIONS_MAX_LIMIT = 500
_COSTS_DEFAULT_DAYS = 30
_COSTS_DAY_OPTIONS: tuple[int, ...] = (7, 30, 90, 180, 365)
_SQL_CONFIRM_PHRASE = "I UNDERSTAND"
_SQL_MAX_PARAMS = 64

_PROPOSAL_TABS: tuple[dict[str, str], ...] = (
    {"key": "pending", "label": "Pending"},
    {"key": "approved", "label": "Approved"},
    {"key": "rejected", "label": "Rejected"},
)
_PROPOSAL_TAB_KEYS: tuple[str, ...] = tuple(t["key"] for t in _PROPOSAL_TABS)


def _proposals_category_or_none(value: str) -> str | None:
    """Normalise the category dropdown — empty / unknown → ``None``."""
    if not value:
        return None
    if value not in VALID_PROPOSAL_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category must be one of {VALID_PROPOSAL_CATEGORIES}",
        )
    return value


async def _fetch_detail_rows(
    conn: asyncpg.Connection,
    summaries: list[ProposalSummary],
) -> dict[str, ProposalDetail]:
    """Pre-fetch full proposal rows so card templates can render jsonb fields."""
    result: dict[str, ProposalDetail] = {}
    for summary in summaries:
        detail = await fetch_proposal_detail(conn, summary.id)
        if detail is not None:
            result[str(summary.id)] = detail
    return result


def _truthy(value: str) -> bool:
    """Form-field truth value (``"true"``/``"1"``/``"on"`` are true)."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _proposal_card_response(
    request: Request,
    *,
    detail: ProposalDetail | None,
    flash: str,
) -> HTMLResponse:
    """Render a refreshed proposal card with a flash toast trigger."""
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    flash_payload = json.dumps(
        {"flash": {"kind": "success", "message": flash}},
        separators=(",", ":"),
    )
    return templates.TemplateResponse(
        request,
        "components/_proposal_card.html",
        {
            "request": request,
            "proposal": detail,
            "details": {str(detail.id): detail},
            "stand_alone": True,
        },
        headers={"HX-Trigger": flash_payload},
    )


def _decode_sql_parameters(raw: str) -> list[object]:
    """Parse the optional ``parameters`` form field (JSON array of bind values).

    Empty / whitespace input is normalised to ``[]``. Anything that doesn't
    decode to a JSON array, or exceeds ``_SQL_MAX_PARAMS`` items, raises a
    422 — the same surface as the JSON ``/admin/sql/*`` routers.
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"parameters: invalid JSON — {exc.msg}",
        ) from exc
    if not isinstance(decoded, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="parameters must be a JSON array",
        )
    if len(decoded) > _SQL_MAX_PARAMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"parameters: at most {_SQL_MAX_PARAMS} values are allowed",
        )
    return list(decoded)


def _new_uuid7() -> str:
    """Return a UUIDv7 string (48-bit unix-ms timestamp + 74 random bits).

    Python 3.12 ships UUIDs 1/3/4/5 but not 7; we construct one by hand so
    the admin UI doesn't carry a third-party dep for one helper. Layout per
    `RFC 9562 §5.7 <https://www.rfc-editor.org/rfc/rfc9562#section-5.7>`__.
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits of unix-millis
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (ms & 0xFFFFFFFFFFFF) << 80
        | (0x7 << 76)
        | (rand_a & 0xFFF) << 64
        | (0b10 << 62)
        | (rand_b & ((1 << 62) - 1))
    )
    return str(UUID(int=value))


def _prefers_html(request: Request) -> bool:
    """Return ``True`` when the client's Accept header prefers HTML over JSON.

    Browsers send ``text/html,application/xhtml+xml,…``; the httpx-based
    integration tests send no ``Accept`` header (defaults to ``*/*``) — so
    the rule is: HTML iff ``text/html`` appears explicitly.
    """
    return "text/html" in request.headers.get("accept", "").lower()


def _clamp_limit(value: int) -> int:
    """Clamp a user-supplied limit into ``[_AUDIT_MIN_LIMIT, _AUDIT_MAX_LIMIT]``."""
    return max(_AUDIT_MIN_LIMIT, min(_AUDIT_MAX_LIMIT, int(value)))


def _blank_to_none(value: str | None) -> str | None:
    """Treat empty / whitespace-only form fields as ``None`` for SQL filters."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(slots=True)
class _ViolationFilters:
    """Filter values echoed back into the violations filter form."""

    agent_id: str | None = None
    severity: str | None = None
    unresolved_only: bool = True
    limit: int = 50


@dataclass(slots=True)
class _AuditFilters:
    """Filter values echoed back into the audit filter form."""

    entity_id: str | None = None
    actor: str | None = None
    since: datetime | None = None
    limit: int = 50

    @property
    def since_input(self) -> str:
        """Format ``since`` for an ``<input type="datetime-local">`` value."""
        if self.since is None:
            return ""
        return self.since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


@dataclass(slots=True)
class DashboardStats:
    """Stat cards rendered on ``/admin/`` and the htmx polling fragment."""

    pending_orders_count: int
    active_agents_count: int
    today_cost_usd: Decimal
    today_model_cost_usd: Decimal
    today_api_cost_usd: Decimal
    last_checkpoint_signing_ts: datetime | None
    last_checkpoint_row_count: int | None
    last_checkpoint_id: str | None
    today: date


async def _fetch_dashboard_stats(conn: asyncpg.Connection) -> DashboardStats:
    """Run the four counter queries in a single transaction-free batch."""
    today = datetime.now(tz=UTC).date()

    pending_orders = await conn.fetchval(
        """
        SELECT COUNT(*)::bigint
          FROM theeyebeta.orders
         WHERE status = 'pending_approval'
        """,
    )
    active_agents = await conn.fetchval(
        """
        SELECT COUNT(*)::bigint
          FROM theeyebeta.agents
         WHERE active = TRUE
        """,
    )
    cost_row = await conn.fetchrow(
        """
        WITH mr AS (
            SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd
              FROM theeyebeta.model_runs
             WHERE created_at >= $1::date
               AND created_at <  ($1::date + interval '1 day')
        ),
        ac AS (
            SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd
              FROM theeyebeta.api_costs
             WHERE ts = $1::date
        )
        SELECT mr.cost_usd AS model_cost_usd,
               ac.cost_usd AS api_cost_usd
          FROM mr, ac
        """,
        today,
    )
    checkpoint_row = await conn.fetchrow(
        """
        SELECT checkpoint_id, signing_ts, row_count
          FROM theeyebeta.audit_checkpoints
         ORDER BY signing_ts DESC
         LIMIT 1
        """,
    )

    model_cost = _to_decimal(cost_row["model_cost_usd"]) if cost_row else Decimal("0")
    api_cost = _to_decimal(cost_row["api_cost_usd"]) if cost_row else Decimal("0")

    return DashboardStats(
        pending_orders_count=int(pending_orders or 0),
        active_agents_count=int(active_agents or 0),
        today_cost_usd=(model_cost + api_cost),
        today_model_cost_usd=model_cost,
        today_api_cost_usd=api_cost,
        last_checkpoint_signing_ts=checkpoint_row["signing_ts"] if checkpoint_row else None,
        last_checkpoint_row_count=(int(checkpoint_row["row_count"]) if checkpoint_row else None),
        last_checkpoint_id=(str(checkpoint_row["checkpoint_id"]) if checkpoint_row else None),
        today=today,
    )


def _to_decimal(raw: object) -> Decimal:
    """Cast asyncpg numeric output to a non-null Decimal."""
    if raw is None:
        return Decimal("0")
    if isinstance(raw, Decimal):
        return raw
    return Decimal(str(raw))


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


async def _find_agent(conn: asyncpg.Connection, agent_id: str) -> AgentSummary:
    """Return the single :class:`AgentSummary` for ``agent_id`` or raise 404."""
    agents = await fetch_agents_summary(conn)
    for agent in agents:
        if agent.id == agent_id:
            return agent
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Agent not found",
    )


def register_views_routes(limiter: Limiter) -> APIRouter:
    """Attach dashboard page + htmx fragment / action routes."""

    @router.get("/", response_class=HTMLResponse)
    async def view_dashboard(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        """Render the operator dashboard at ``/admin/``."""
        stats = await _fetch_dashboard_stats(conn)
        log.info("admin_dashboard_rendered", sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            page_context(
                request,
                active="dashboard",
                title="Dashboard",
                extra={
                    "stats": stats,
                    "grafana_overview_url": settings.grafana_overview_url,
                    "daily_backtest_configured": bool(
                        settings.daily_backtest_strategy_id,
                    ),
                    "daily_backtest_strategy_id": settings.daily_backtest_strategy_id,
                    "daily_backtest_days": settings.daily_backtest_days,
                    "audit_verify_hours": settings.audit_verify_hours,
                },
            ),
        )

    @router.get("/fragments/stats", response_class=HTMLResponse)
    async def fragment_stats(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Re-render the 4 stat cards (htmx polling / post-action refresh)."""
        stats = await _fetch_dashboard_stats(conn)
        log.info("admin_dashboard_stats_refreshed", sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "components/_stat_cards.html",
            {"request": request, "stats": stats},
        )

    @router.post("/actions/verify-audit-chain", response_class=HTMLResponse)
    @limiter.limit("20/minute")
    async def action_verify_audit_chain(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        """Invoke audit-service verify over the last ``audit_verify_hours`` window."""
        now = datetime.now(tz=UTC)
        from_ts = now - timedelta(hours=settings.audit_verify_hours)
        verify: AuditVerifyResponse | None = None
        error: str | None = None
        try:
            verify = await call_audit_service_verify(settings, from_ts=from_ts, to_ts=now)
            await write_audit_log(
                conn,
                actor=_actor(user),
                action="verify.audit_chain",
                entity_type="audit_chain",
                entity_id=f"{from_ts.isoformat()}..{now.isoformat()}",
                payload={
                    "ok": verify.ok,
                    "mismatch_at_id": verify.mismatch_at_id,
                    "rows_checked": verify.rows_checked,
                },
            )
            log.info(
                "admin_dashboard_audit_verify",
                ok=verify.ok,
                rows_checked=verify.rows_checked,
                sub=user["sub"],
            )
        except Exception as exc:  # noqa: BLE001 — surface failure on the card
            error = _short_error(exc)
            log.error("admin_dashboard_audit_verify_failed", error=error, sub=user["sub"])

        stats = await _fetch_dashboard_stats(conn)
        return templates.TemplateResponse(
            request,
            "components/_audit_verify_card.html",
            {
                "request": request,
                "stats": stats,
                "verify": verify,
                "verify_error": error,
                "audit_verify_hours": settings.audit_verify_hours,
            },
        )

    @router.post("/actions/run-daily-backtest", response_class=HTMLResponse)
    @limiter.limit("20/minute")
    async def action_run_daily_backtest(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        """Trigger ``backtest-engine POST /backtest/run`` for the configured strategy."""
        if not settings.daily_backtest_strategy_id:
            return _flash_response(
                request,
                kind="warn",
                message=(
                    "Daily backtest is not configured — set "
                    "ADMIN_DAILY_BACKTEST_STRATEGY_ID to enable this action."
                ),
            )

        end_d = datetime.now(tz=UTC).date()
        start_d = end_d - timedelta(days=settings.daily_backtest_days - 1)
        payload: dict[str, object] = {
            "strategy_id": settings.daily_backtest_strategy_id,
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
        }
        if settings.daily_backtest_universe:
            payload["universe"] = settings.daily_backtest_universe

        url = f"{settings.backtest_engine_url.rstrip('/')}/backtest/run"
        try:
            async with httpx.AsyncClient(timeout=_BACKTEST_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            log.error("admin_dashboard_backtest_unreachable", url=url, error=str(exc))
            return _flash_response(
                request,
                kind="error",
                message="backtest-engine is unreachable — check `tb status backtest-engine`.",
            )

        if response.status_code >= 400:
            log.error(
                "admin_dashboard_backtest_failed",
                status=response.status_code,
                body=response.text[:200],
                sub=user["sub"],
            )
            return _flash_response(
                request,
                kind="error",
                message=f"backtest-engine returned {response.status_code}.",
            )

        data = response.json()
        run_id = str(data.get("backtest_run_id") or "").strip()
        if not run_id:
            return _flash_response(
                request,
                kind="error",
                message="backtest-engine response missing backtest_run_id.",
            )

        await write_audit_log(
            conn,
            actor=_actor(user),
            action="start.backtest",
            entity_type="backtest_run",
            entity_id=run_id,
            payload={**payload, "backtest_run_id": run_id, "trigger": "dashboard"},
        )
        log.info(
            "admin_dashboard_backtest_started",
            backtest_run_id=run_id,
            strategy_id=settings.daily_backtest_strategy_id,
            sub=user["sub"],
        )
        return _flash_response(
            request,
            kind="ok",
            message=f"Backtest {run_id[:8]}… queued for {start_d}→{end_d}.",
        )

    @router.get("/orders", response_class=HTMLResponse)
    async def view_orders(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Render the pending-orders queue at ``/admin/orders``."""
        rows = await conn.fetch(
            f"""
            {_SELECT_ORDER}
             WHERE o.status = 'pending_approval'
             ORDER BY o.created_at DESC
            """,
        )
        orders = [_row_to_order_view(row) for row in rows]
        log.info("admin_orders_page_rendered", count=len(orders), sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "orders.html",
            page_context(
                request,
                active="orders",
                title="Pending orders",
                extra={"orders": orders, "pending_total": len(orders)},
            ),
        )

    @router.get(
        "/orders/fragments/{order_id}/rationale",
        response_class=HTMLResponse,
    )
    async def fragment_order_rationale(
        request: Request,
        order_id: UUID,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Return the fully-expanded agent rationale for one order."""
        view = await _load_order_view(conn, order_id)
        log.info(
            "admin_orders_rationale_expanded",
            order_id=str(order_id),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_order_rationale.html",
            {"request": request, "order": view, "expanded": True},
        )

    @router.get(
        "/orders/fragments/{order_id}/rationale-snippet",
        response_class=HTMLResponse,
    )
    async def fragment_order_rationale_snippet(
        request: Request,
        order_id: UUID,
        user: CurrentUser,  # noqa: ARG001 — logged via dep
        conn: DbConn,
    ) -> HTMLResponse:
        """Return the truncated rationale block (collapse target)."""
        view = await _load_order_view(conn, order_id)
        return templates.TemplateResponse(
            request,
            "components/_order_rationale.html",
            {"request": request, "order": view, "expanded": False},
        )

    @router.get(
        "/orders/fragments/{order_id}/reject-modal",
        response_class=HTMLResponse,
    )
    async def fragment_order_reject_modal(
        request: Request,
        order_id: UUID,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Return the reject-reason modal pre-filled with the order context."""
        view = await _load_order_view(conn, order_id)
        log.info(
            "admin_orders_reject_modal_opened",
            order_id=str(order_id),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_order_reject_modal.html",
            {"request": request, "order": view},
        )

    @router.post(
        "/orders/fragments/{order_id}/approve",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_order_approve(
        request: Request,  # noqa: ARG001 — required by slowapi
        order_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        nats: NatsClient,
        note: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        """Approve a pending order and return the updated row HTML."""
        await approve_pending_order(
            conn,
            nats,
            order_id=order_id,
            actor=_actor(user),
            note=note,
        )
        return await _render_order_row_response(request, conn, order_id)

    @router.post(
        "/orders/fragments/{order_id}/reject",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_order_reject(
        request: Request,  # noqa: ARG001 — required by slowapi
        order_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        rejection_reason: Annotated[str, Form(min_length=1, max_length=2000)],
    ) -> HTMLResponse:
        """Reject a pending order and return the updated row HTML."""
        await reject_pending_order(
            conn,
            order_id=order_id,
            actor=_actor(user),
            reason=rejection_reason.strip(),
        )
        return await _render_order_row_response(request, conn, order_id)

    # ---------------------------------------------------------------- Audit page

    @router.get("/audit", response_class=HTMLResponse)
    async def view_audit(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        """Render the audit log page with the first page of entries inline."""
        limit = settings.audit_page_limit
        entries, next_cursor = await fetch_audit_log_page(
            conn,
            entity_id=None,
            actor=None,
            since=None,
            limit=limit,
            cursor=None,
        )
        defaults = _audit_verify_defaults(settings.audit_verify_hours)
        log.info(
            "admin_audit_page_rendered",
            count=len(entries),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "audit.html",
            page_context(
                request,
                active="audit",
                title="Audit log",
                extra={
                    "entries": entries,
                    "rows": [_audit_row_view(e) for e in entries],
                    "next_cursor": next_cursor,
                    "limit": limit,
                    "max_limit": _AUDIT_MAX_LIMIT,
                    "filters": _AuditFilters(),
                    "verify_default_from": defaults[0],
                    "verify_default_to": defaults[1],
                },
            ),
        )

    @router.get("/audit/fragments/log", response_class=HTMLResponse)
    async def fragment_audit_log(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        entity_id: str | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        cursor: int | None = None,
        append: bool = False,
    ) -> HTMLResponse:
        """Return just the audit table (filtered / paginated)."""
        normalized_limit = _clamp_limit(limit)
        filters = _AuditFilters(
            entity_id=_blank_to_none(entity_id),
            actor=_blank_to_none(actor),
            since=since,
            limit=normalized_limit,
        )
        entries, next_cursor = await fetch_audit_log_page(
            conn,
            entity_id=filters.entity_id,
            actor=filters.actor,
            since=filters.since,
            limit=normalized_limit,
            cursor=cursor,
        )
        log.info(
            "admin_audit_log_fragment",
            count=len(entries),
            sub=user["sub"],
            append=append,
        )
        template = "components/_audit_rows.html" if append else "components/_audit_table.html"
        return templates.TemplateResponse(
            request,
            template,
            {
                "request": request,
                "rows": [_audit_row_view(e) for e in entries],
                "next_cursor": next_cursor,
                "limit": normalized_limit,
                "filters": filters,
            },
        )

    # ---------------------------------------------------------------- Agents page

    @router.get("/agents", include_in_schema=False, response_model=None)
    async def view_agents(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse | AgentsListResponse:
        """Agents page (HTML) or list (JSON) based on the ``Accept`` header."""
        agents = await fetch_agents_summary(conn)
        if not _prefers_html(request):
            log.info("admin_agents_listed", count=len(agents), sub=user["sub"])
            return AgentsListResponse(agents=agents)
        log.info("admin_agents_page_rendered", count=len(agents), sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "agents.html",
            page_context(
                request,
                active="agents",
                title="Agents",
                extra={"agents": agents},
            ),
        )

    @router.get("/agents/fragments/{agent_id}/runs", response_class=HTMLResponse)
    async def fragment_agent_runs(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        agent_id: str,
    ) -> HTMLResponse:
        """Render the "Recent runs" right-pane tab for one agent."""
        agent = await _find_agent(conn, agent_id)
        runs = await fetch_agent_runs(conn, agent_id, _AGENT_RUNS_LIMIT)
        log.info(
            "admin_agent_runs_fragment",
            agent_id=agent_id,
            count=len(runs.runs),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_agent_right_panel.html",
            {
                "request": request,
                "agent": agent,
                "tab": "runs",
                "runs": runs.runs,
                "runs_limit": runs.limit,
            },
        )

    @router.get(
        "/agents/fragments/{agent_id}/constitution",
        response_class=HTMLResponse,
    )
    async def fragment_agent_constitution(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        agent_id: str,
    ) -> HTMLResponse:
        """Render the "Constitution" right-pane tab for one agent."""
        agent = await _find_agent(conn, agent_id)
        try:
            constitution = await read_agent_constitution(
                conn,
                settings.repo_root_path(),
                agent_id,
            )
            content = constitution.content
            constitution_path = constitution.constitution_path
            constitution_error: str | None = None
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                raise
            content = ""
            constitution_path = agent.constitution_path
            constitution_error = str(exc.detail)
        log.info(
            "admin_agent_constitution_fragment",
            agent_id=agent_id,
            sub=user["sub"],
            ok=constitution_error is None,
        )
        return templates.TemplateResponse(
            request,
            "components/_agent_right_panel.html",
            {
                "request": request,
                "agent": agent,
                "tab": "constitution",
                "constitution_content": content,
                "constitution_path": constitution_path,
                "constitution_error": constitution_error,
            },
        )

    @router.get(
        "/agents/fragments/{agent_id}/run-modal",
        response_class=HTMLResponse,
    )
    async def fragment_agent_run_modal(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate
        conn: DbConn,
        agent_id: str,
    ) -> HTMLResponse:
        """Render the Run Now modal form for one agent."""
        agent = await _find_agent(conn, agent_id)
        return templates.TemplateResponse(
            request,
            "components/_agent_run_modal.html",
            {"request": request, "agent": agent},
        )

    # ------------------------------------------------------------ Costs page

    @router.get("/costs", response_class=HTMLResponse)
    async def view_costs(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Render the costs page (daily chart + per-agent doughnut + MTD tables)."""
        days = _COSTS_DEFAULT_DAYS
        month = current_month_key()
        daily = await fetch_daily_costs(conn, days)
        by_agent = await fetch_costs_by_agent(conn, month)
        by_vendor = await fetch_costs_by_vendor(conn, month)
        log.info(
            "admin_costs_page_rendered",
            days=days,
            month=month,
            daily_total=str(daily.total_cost_usd),
            agent_count=len(by_agent.agents),
            vendor_rows=len(by_vendor),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "costs.html",
            page_context(
                request,
                active="costs",
                title="Costs",
                extra={
                    "daily": daily,
                    "by_agent": by_agent,
                    "by_vendor": by_vendor,
                    "month": month,
                    "days": days,
                    "day_options": list(_COSTS_DAY_OPTIONS),
                    "month_options": _recent_month_options(months_back=6),
                    "daily_chart_config": _daily_chart_config(daily),
                    "agent_chart_config": _agent_chart_config(by_agent),
                },
            ),
        )

    @router.get("/costs/fragments/daily", response_class=HTMLResponse)
    async def fragment_costs_daily(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        days: int = _COSTS_DEFAULT_DAYS,
    ) -> HTMLResponse:
        """Daily chart fragment, swapped when the operator changes the window."""
        daily = await fetch_daily_costs(conn, days)
        log.info(
            "admin_costs_daily_fragment",
            days=days,
            total=str(daily.total_cost_usd),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_costs_daily_chart.html",
            {
                "request": request,
                "daily": daily,
                "days": days,
                "day_options": list(_COSTS_DAY_OPTIONS),
                "daily_chart_config": _daily_chart_config(daily),
            },
        )

    @router.get("/costs/fragments/by-agent", response_class=HTMLResponse)
    async def fragment_costs_by_agent(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        month: str = "",
    ) -> HTMLResponse:
        """Per-agent doughnut + table fragment, swapped on month change."""
        target_month = month or current_month_key()
        parse_month(target_month)  # 422 if malformed
        by_agent = await fetch_costs_by_agent(conn, target_month)
        log.info(
            "admin_costs_agent_fragment",
            month=target_month,
            agent_count=len(by_agent.agents),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_costs_agent_chart.html",
            {
                "request": request,
                "by_agent": by_agent,
                "month": target_month,
                "month_options": _recent_month_options(months_back=6),
                "agent_chart_config": _agent_chart_config(by_agent),
            },
        )

    @router.get("/costs/fragments/vendor", response_class=HTMLResponse)
    async def fragment_costs_vendor(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        month: str = "",
    ) -> HTMLResponse:
        """MTD vendor table fragment, swapped on month change."""
        target_month = month or current_month_key()
        parse_month(target_month)
        by_vendor = await fetch_costs_by_vendor(conn, target_month)
        log.info(
            "admin_costs_vendor_fragment",
            month=target_month,
            vendor_rows=len(by_vendor),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_costs_vendor_table.html",
            {
                "request": request,
                "by_vendor": by_vendor,
                "month": target_month,
                "month_options": _recent_month_options(months_back=6),
            },
        )

    # ------------------------------------------------------------ SQL playground

    @router.get("/sql", response_class=HTMLResponse)
    async def view_sql(
        request: Request,
        user: CurrentUser,
    ) -> HTMLResponse:
        """Render the SQL playground (editor + radio mode + empty result pane)."""
        log.info("admin_sql_page_rendered", sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "sql.html",
            page_context(
                request,
                active="sql",
                title="SQL",
                extra={
                    "query_max_rows": QUERY_MAX_ROWS,
                    "query_timeout_seconds": int(QUERY_TIMEOUT_SECONDS),
                },
            ),
        )

    @router.post("/sql/fragments/query", response_class=HTMLResponse)
    @limiter.limit("20/minute")
    async def fragment_sql_query(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        statement: Annotated[str, Form(min_length=1, max_length=20_000)],
        parameters: Annotated[str, Form(max_length=8_000)] = "",
    ) -> HTMLResponse:
        """Run a read-only SELECT and return the result table partial."""
        params = _decode_sql_parameters(parameters)
        try:
            response = await run_select_statement(conn, statement, params)
        except HTTPException as exc:
            return templates.TemplateResponse(
                request,
                "components/_sql_error.html",
                {
                    "request": request,
                    "status_code": exc.status_code,
                    "detail": str(exc.detail),
                    "statement": statement,
                },
                status_code=200,
            )

        log.info(
            "admin_sql_page_query",
            sub=user["sub"],
            row_count=response.row_count,
            truncated=response.truncated,
            elapsed_ms=response.elapsed_ms,
        )
        return templates.TemplateResponse(
            request,
            "components/_sql_query_result.html",
            {
                "request": request,
                "result": response,
                "max_rows": QUERY_MAX_ROWS,
            },
        )

    @router.get("/sql/fragments/confirm", response_class=HTMLResponse)
    async def fragment_sql_confirm(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate only
    ) -> HTMLResponse:
        """Return the "I UNDERSTAND" confirmation modal with a fresh idem key."""
        return templates.TemplateResponse(
            request,
            "components/_sql_confirm_modal.html",
            {
                "request": request,
                "idempotency_key": _new_uuid7(),
                "confirm_phrase": _SQL_CONFIRM_PHRASE,
            },
        )

    @router.post("/sql/fragments/execute", response_class=HTMLResponse)
    @limiter.limit("20/minute")
    async def fragment_sql_execute(
        request: Request,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
        conn: DbConn,
        statement: Annotated[str, Form(min_length=1, max_length=20_000)],
        idempotency_key: Annotated[str, Form(min_length=1, max_length=64)],
        confirm_phrase: Annotated[str, Form(min_length=1, max_length=64)],
        parameters: Annotated[str, Form(max_length=8_000)] = "",
    ) -> HTMLResponse:
        """Run a write statement after the operator typed the confirm phrase."""
        if confirm_phrase.strip() != _SQL_CONFIRM_PHRASE:
            return templates.TemplateResponse(
                request,
                "components/_sql_error.html",
                {
                    "request": request,
                    "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "detail": (f"Confirmation phrase mismatch — expected '{_SQL_CONFIRM_PHRASE}'."),
                    "statement": statement,
                },
                status_code=200,
            )

        params = _decode_sql_parameters(parameters)
        actor = f"admin-api:{user['sub']}"
        try:
            response = await run_write_statement(
                conn,
                statement,
                params,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        except HTTPException as exc:
            return templates.TemplateResponse(
                request,
                "components/_sql_error.html",
                {
                    "request": request,
                    "status_code": exc.status_code,
                    "detail": str(exc.detail),
                    "statement": statement,
                },
                status_code=200,
            )

        log.info(
            "admin_sql_page_execute",
            sub=user["sub"],
            command_tag=response.command_tag,
            rows_affected=response.rows_affected,
            elapsed_ms=response.elapsed_ms,
            idempotency_key=response.idempotency_key,
        )
        return templates.TemplateResponse(
            request,
            "components/_sql_execute_result.html",
            {
                "request": request,
                "result": response,
            },
            headers={
                "HX-Trigger": (
                    f'{{"flash": {{"kind": "success", '
                    f'"message": "Statement executed — rows affected: '
                    f'{response.rows_affected}."}}}}'
                ),
            },
        )

    # ------------------------------------------------------------ Proposals page

    @router.get("/proposals", response_class=HTMLResponse)
    async def view_proposals(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        category: str = "",
    ) -> HTMLResponse:
        """Render the proposals page with three tabs (pending/approved/rejected)."""
        active_status = "pending"
        active_category = _proposals_category_or_none(category)
        page = await fetch_proposals_page(
            conn,
            proposal_status=active_status,
            category=active_category,
            limit=PROPOSALS_DEFAULT_LIMIT,
        )
        # Fetch detail rows for cards so jsonb fields (estimated_impact, evidence)
        # are available without an N+1 follow-up; for an MVP the proposal lists
        # are short (<=100 rows), so this stays inside the same hot path.
        detail_rows = await _fetch_detail_rows(conn, page.proposals)
        log.info(
            "admin_proposals_page_rendered",
            status=active_status,
            category=active_category,
            count=len(page.proposals),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "proposals.html",
            page_context(
                request,
                active="proposals",
                title="Proposals",
                extra={
                    "active_status": active_status,
                    "active_category": active_category or "",
                    "tabs": _PROPOSAL_TABS,
                    "categories": list(VALID_PROPOSAL_CATEGORIES),
                    "page": page,
                    "details": detail_rows,
                },
            ),
        )

    @router.get("/proposals/fragments/tab", response_class=HTMLResponse)
    async def fragment_proposals_tab(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        proposal_status: Annotated[str, Query(alias="status")] = "pending",
        category: str = "",
    ) -> HTMLResponse:
        """Cards-list fragment for one of the three tabs."""
        if proposal_status not in _PROPOSAL_TAB_KEYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status must be one of {_PROPOSAL_TAB_KEYS}",
            )
        active_category = _proposals_category_or_none(category)
        page = await fetch_proposals_page(
            conn,
            proposal_status=proposal_status,
            category=active_category,
            limit=PROPOSALS_DEFAULT_LIMIT,
        )
        detail_rows = await _fetch_detail_rows(conn, page.proposals)
        log.info(
            "admin_proposals_tab_fragment",
            status=proposal_status,
            category=active_category,
            count=len(page.proposals),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_proposals_tab_list.html",
            {
                "request": request,
                "active_status": proposal_status,
                "active_category": active_category or "",
                "page": page,
                "details": detail_rows,
            },
        )

    @router.get(
        "/proposals/fragments/{proposal_id}/approve-modal",
        response_class=HTMLResponse,
    )
    async def fragment_proposal_approve_modal(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate only
        conn: DbConn,
        proposal_id: UUID,
    ) -> HTMLResponse:
        """Return the approve modal with defaults pre-filled from the proposal."""
        detail = await fetch_proposal_detail(conn, proposal_id)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found",
            )
        today = date.today()  # noqa: DTZ011 — calendar boundary
        return templates.TemplateResponse(
            request,
            "components/_proposal_approve_modal.html",
            {
                "request": request,
                "proposal": detail,
                "default_end_date": today.isoformat(),
                "default_start_date": (today - timedelta(days=365)).isoformat(),
                "default_strategy_id": (
                    detail.target if detail.category == "strategy_param" else ""
                ),
            },
        )

    @router.post(
        "/proposals/fragments/{proposal_id}/approve",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_proposal_approve(
        request: Request,  # noqa: ARG001 — required by slowapi
        user: CurrentUser,
        conn: DbConn,
        nats: NatsClient,
        proposal_id: UUID,
        review_notes: Annotated[str, Form(max_length=2000)] = "",
        skip_backtest: Annotated[str, Form()] = "",
        strategy_id: Annotated[str, Form(max_length=200)] = "",
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        universe: Annotated[str, Form(max_length=200)] = "sp500",
    ) -> HTMLResponse:
        """Submit an approve from the modal — returns the refreshed card."""
        body_kwargs: dict[str, Any] = {
            "review_notes": review_notes or None,
            "skip_backtest": _truthy(skip_backtest),
            "universe": universe or None,
        }
        if strategy_id.strip():
            body_kwargs["strategy_id"] = strategy_id.strip()
        if start_date.strip():
            try:
                body_kwargs["start_date"] = date.fromisoformat(start_date.strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"start_date: {exc}",
                ) from exc
        if end_date.strip():
            try:
                body_kwargs["end_date"] = date.fromisoformat(end_date.strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"end_date: {exc}",
                ) from exc

        body = ApproveProposalRequest(**body_kwargs)
        actor = f"admin-api:{user['sub']}"
        await approve_proposal_impl(
            conn,
            nats,
            proposal_id=proposal_id,
            body=body,
            actor=actor,
        )
        detail = await fetch_proposal_detail(conn, proposal_id)
        return _proposal_card_response(
            request,
            detail=detail,
            flash=(
                "Proposal approved."
                + (" Validation backtest queued." if not body.skip_backtest else "")
            ),
        )

    @router.get(
        "/proposals/fragments/{proposal_id}/reject-modal",
        response_class=HTMLResponse,
    )
    async def fragment_proposal_reject_modal(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate only
        conn: DbConn,
        proposal_id: UUID,
    ) -> HTMLResponse:
        """Return the reject modal (requires ``review_notes``)."""
        detail = await fetch_proposal_detail(conn, proposal_id)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found",
            )
        return templates.TemplateResponse(
            request,
            "components/_proposal_reject_modal.html",
            {"request": request, "proposal": detail},
        )

    @router.post(
        "/proposals/fragments/{proposal_id}/reject",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_proposal_reject(
        request: Request,  # noqa: ARG001 — required by slowapi
        user: CurrentUser,
        conn: DbConn,
        proposal_id: UUID,
        review_notes: Annotated[str, Form(min_length=1, max_length=2000)],
    ) -> HTMLResponse:
        """Submit a reject from the modal — returns the refreshed card."""
        actor = f"admin-api:{user['sub']}"
        body = RejectProposalRequest(review_notes=review_notes)
        await reject_proposal_impl(
            conn,
            proposal_id=proposal_id,
            body=body,
            actor=actor,
        )
        detail = await fetch_proposal_detail(conn, proposal_id)
        return _proposal_card_response(
            request,
            detail=detail,
            flash="Proposal rejected.",
        )

    @router.get(
        "/proposals/fragments/{proposal_id}/backtest-status",
        response_class=HTMLResponse,
    )
    async def fragment_proposal_backtest_status(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate only
        conn: DbConn,
        proposal_id: UUID,
    ) -> HTMLResponse:
        """Poll the validation backtest for an approved proposal."""
        detail = await fetch_proposal_detail(conn, proposal_id)
        if detail is None or detail.validation_backtest_id is None:
            return templates.TemplateResponse(
                request,
                "components/_proposal_backtest_status.html",
                {
                    "request": request,
                    "proposal_id": str(proposal_id),
                    "backtest_id": None,
                    "status": None,
                    "polling": False,
                },
            )
        bt = await fetch_backtest_status(conn, detail.validation_backtest_id)
        terminal = bt is None or bt["status"] in {"completed", "failed", "cancelled"}
        return templates.TemplateResponse(
            request,
            "components/_proposal_backtest_status.html",
            {
                "request": request,
                "proposal_id": str(proposal_id),
                "backtest_id": str(detail.validation_backtest_id),
                "status": bt["status"] if bt else "unknown",
                "polling": not terminal,
            },
        )

    # ------------------------------------------------------------ Violations page

    @router.get("/violations", response_class=HTMLResponse)
    async def view_violations(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
    ) -> HTMLResponse:
        """Render the guard violations page with the first page of rows inline.

        Default filter is ``unresolved_only=true`` per spec — operators
        usually arrive here looking for open work.
        """
        filters = _ViolationFilters(
            unresolved_only=True,
            limit=_VIOLATIONS_DEFAULT_LIMIT,
        )
        entries, next_cursor = await fetch_guard_violations_page(
            conn,
            agent_id=None,
            severity=None,
            unresolved_only=filters.unresolved_only,
            limit=filters.limit,
            cursor=None,
        )
        log.info(
            "admin_violations_page_rendered",
            count=len(entries),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "violations.html",
            page_context(
                request,
                active="violations",
                title="Guard violations",
                extra={
                    "rows": entries,
                    "next_cursor": next_cursor,
                    "filters": filters,
                    "valid_severities": list(VALID_SEVERITIES),
                },
            ),
        )

    @router.get("/violations/fragments/list", response_class=HTMLResponse)
    async def fragment_violations_list(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        agent_id: str | None = None,
        severity: str | None = None,
        unresolved_only: bool = True,
        limit: int = _VIOLATIONS_DEFAULT_LIMIT,
        cursor: int | None = None,
        append: bool = False,
    ) -> HTMLResponse:
        """Return just the violations table (filtered / paginated)."""
        normalized_limit = max(1, min(_VIOLATIONS_MAX_LIMIT, int(limit)))
        normalized_severity = _blank_to_none(severity)
        validate_severity(normalized_severity)
        filters = _ViolationFilters(
            agent_id=_blank_to_none(agent_id),
            severity=normalized_severity,
            unresolved_only=bool(unresolved_only),
            limit=normalized_limit,
        )
        entries, next_cursor = await fetch_guard_violations_page(
            conn,
            agent_id=filters.agent_id,
            severity=filters.severity,
            unresolved_only=filters.unresolved_only,
            limit=normalized_limit,
            cursor=cursor,
        )
        log.info(
            "admin_violations_list_fragment",
            count=len(entries),
            agent_id=filters.agent_id,
            severity=filters.severity,
            unresolved_only=filters.unresolved_only,
            append=append,
            sub=user["sub"],
        )
        template = (
            "components/_violations_rows.html" if append else "components/_violations_table.html"
        )
        return templates.TemplateResponse(
            request,
            template,
            {
                "request": request,
                "rows": entries,
                "next_cursor": next_cursor,
                "filters": filters,
            },
        )

    @router.get(
        "/violations/fragments/{violation_id}/resolve-modal",
        response_class=HTMLResponse,
    )
    async def fragment_violation_resolve_modal(
        request: Request,
        user: CurrentUser,  # noqa: ARG001 — auth gate
        conn: DbConn,
        violation_id: int,
    ) -> HTMLResponse:
        """Render the resolve-note modal form for one violation."""
        violation = await fetch_guard_violation(conn, violation_id)
        if violation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Guard violation not found",
            )
        if violation.resolved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Guard violation already resolved",
            )
        return templates.TemplateResponse(
            request,
            "components/_violation_resolve_modal.html",
            {"request": request, "row": violation},
        )

    @router.post(
        "/violations/fragments/{violation_id}/resolve",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_violation_resolve(
        request: Request,  # noqa: ARG001 — required by slowapi
        user: CurrentUser,
        conn: DbConn,
        violation_id: int,
        note: Annotated[str, Form(max_length=2000)] = "",
    ) -> HTMLResponse:
        """Resolve a violation and return its updated row HTML."""
        stripped = note.strip()
        await resolve_guard_violation_impl(
            conn,
            violation_id=violation_id,
            actor=_actor(user),
            note=stripped or None,
        )
        refreshed = await fetch_guard_violation(conn, violation_id)
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Guard violation disappeared after resolve",
            )
        log.info(
            "admin_violation_resolve_fragment",
            violation_id=violation_id,
            sub=user["sub"],
        )
        response = templates.TemplateResponse(
            request,
            "components/_violation_row.html",
            {"request": request, "row": refreshed},
        )
        response.headers["HX-Trigger"] = (
            f'{{"flash": {{"kind": "success", "message": "Violation {violation_id} resolved."}}}}'
        )
        return response

    @router.post(
        "/agents/fragments/{agent_id}/run",
        response_class=HTMLResponse,
    )
    @limiter.limit("20/minute")
    async def fragment_agent_run(
        request: Request,  # noqa: ARG001 — required by slowapi
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        agent_id: str,
        snapshot_id: Annotated[UUID, Form()],
        kind: Annotated[str, Form(min_length=1, max_length=64)],
        prompt: Annotated[str, Form(max_length=8000)] = "",
    ) -> HTMLResponse:
        """Trigger an agent run; return a flash card with the result."""
        agent_messages: list[AgentMessageDTO] = []
        prompt_stripped = prompt.strip()
        if prompt_stripped:
            agent_messages.append(AgentMessageDTO(role="user", content=prompt_stripped))
        body = RunAgentRequest(
            snapshot_id=snapshot_id,
            kind=kind.strip(),
            agent_messages=agent_messages,
        )
        try:
            result = await trigger_agent_run_impl(
                conn,
                settings,
                agent_id=agent_id,
                body=body,
                actor=_actor(user),
            )
        except HTTPException as exc:
            log.warning(
                "admin_agent_run_fragment_failed",
                agent_id=agent_id,
                status=exc.status_code,
                detail=str(exc.detail),
                sub=user["sub"],
            )
            return _flash_response(
                request,
                kind="error",
                message=f"Run failed ({exc.status_code}): {_short_error(exc)}",
            )
        log.info(
            "admin_agent_run_fragment_ok",
            agent_id=agent_id,
            run_id=result.run_id,
            sub=user["sub"],
        )
        return _flash_response(
            request,
            kind="success",
            message=f"Run started for {agent_id} (run_id={result.run_id}).",
        )

    @router.get("/audit/fragments/verify", response_class=HTMLResponse)
    async def fragment_audit_verify(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
        from_ts: datetime = Query(..., alias="from"),
        to_ts: datetime = Query(..., alias="to"),
    ) -> HTMLResponse:
        """Run audit-service verify for ``[from, to]`` and render the result card."""
        verify: AuditVerifyResponse | None = None
        error: str | None = None
        if to_ts < from_ts:
            error = "'to' must be greater than or equal to 'from'."
        else:
            try:
                verify = await call_audit_service_verify(
                    settings,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
            except Exception as exc:  # noqa: BLE001 — surface to the operator
                error = _short_error(exc)
        log.info(
            "admin_audit_verify_fragment",
            ok=(verify.ok if verify else None),
            sub=user["sub"],
        )
        return templates.TemplateResponse(
            request,
            "components/_audit_verify_result.html",
            {
                "request": request,
                "verify": verify,
                "verify_error": error,
                "from_ts": from_ts,
                "to_ts": to_ts,
            },
        )

    return router


def _flash_response(request: Request, *, kind: str, message: str) -> HTMLResponse:
    """Render a single ``_flash.html`` toast and set the ``HX-Trigger`` header.

    Keeping the toast HTML in the response body (in addition to the
    ``HX-Trigger`` event consumed by ``static/js/app.js``) means the button's
    own ``hx-target`` (the inline ``#flash-target`` slot) gets a server-side
    fallback if the JS handler ever fails.
    """
    response = templates.TemplateResponse(
        request,
        "components/_flash.html",
        {"request": request, "kind": kind, "message": message},
    )
    response.headers["HX-Trigger"] = (
        '{"flash": {"kind": "%s", "message": %r}}'  # noqa: UP031 — header format
        % (kind, message)
    )
    return response


def _short_error(exc: BaseException) -> str:
    """Trim long stack traces / response bodies to keep flash toasts readable."""
    text = str(exc) or exc.__class__.__name__
    return text if len(text) <= 200 else f"{text[:197]}…"


@dataclass(slots=True)
class OrderView:
    """Order shape used by the orders table + row partials.

    Built once via :func:`_row_to_order_view` from a joined ``orders`` row so
    the templates don't need to know about ``asyncpg.Record`` / JSONB parsing.
    """

    id: UUID
    client_order_id: str
    symbol: str
    exchange_code: str | None
    side: str
    order_type: str
    qty: Decimal
    limit_price: Decimal | None
    status: str
    created_at: datetime
    rationale: str | None
    rationale_short: str | None
    rejection_reason: str | None
    approved_by: str | None
    approved_at: datetime | None
    metadata: dict[str, Any]


_RATIONALE_SNIPPET_CHARS = 140


def _row_to_order_view(row: asyncpg.Record) -> OrderView:
    """Map a joined order row + parsed JSONB metadata to :class:`OrderView`."""
    metadata = row["metadata"]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}

    rationale = metadata.get("rationale") or metadata.get("agent_rationale")
    rationale_text = str(rationale).strip() if isinstance(rationale, str) else None
    snippet: str | None = None
    if rationale_text:
        snippet = (
            rationale_text
            if len(rationale_text) <= _RATIONALE_SNIPPET_CHARS
            else rationale_text[:_RATIONALE_SNIPPET_CHARS].rstrip() + "…"
        )

    rejection_reason = metadata.get("rejection_reason")
    rejection_text = str(rejection_reason).strip() if isinstance(rejection_reason, str) else None

    return OrderView(
        id=row["id"],
        client_order_id=row["client_order_id"],
        symbol=row["instrument_symbol"],
        exchange_code=row["exchange_code"],
        side=row["side"],
        order_type=row["order_type"],
        qty=Decimal(str(row["qty"])),
        limit_price=(Decimal(str(row["limit_price"])) if row["limit_price"] is not None else None),
        status=row["status"],
        created_at=row["created_at"],
        rationale=rationale_text,
        rationale_short=snippet,
        rejection_reason=rejection_text,
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        metadata=metadata,
    )


async def _load_order_view(
    conn: asyncpg.Connection,
    order_id: UUID,
) -> OrderView:
    """Fetch one joined order row → :class:`OrderView`. Raises 404 if missing."""
    row = await _fetch_order(conn, order_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    return _row_to_order_view(row)


async def _render_order_row_response(
    request: Request,
    conn: asyncpg.Connection,
    order_id: UUID,
) -> HTMLResponse:
    """Refetch the order and render the table-row partial after a mutation."""
    view = await _load_order_view(conn, order_id)
    return templates.TemplateResponse(
        request,
        "components/_order_row.html",
        {"request": request, "order": view},
    )


@dataclass(slots=True)
class AuditRowView:
    """Audit-log row shape rendered by ``_audit_table.html`` / ``_audit_rows.html``."""

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload_pretty: str
    payload_snippet: str
    payload_truncated: bool
    severity: str


_ACTION_SEVERITY: dict[str, str] = {
    "approve.order": "low",
    "submit.order": "low",
    "reject.order": "medium",
    "approve.proposal": "low",
    "reject.proposal": "medium",
    "verify.audit_chain": "low",
    "resolve.guard_violation": "medium",
    "restart.service": "high",
    "execute.sql": "high",
    "start.backtest": "low",
    "run.agent": "low",
}


def _action_severity(action: str) -> str:
    """Map an audit ``action`` to one of the P-FE-00 severity tones."""
    if action in _ACTION_SEVERITY:
        return _ACTION_SEVERITY[action]
    if action.startswith("execute.") or action.startswith("delete."):
        return "high"
    return "low"


def _audit_row_view(entry: AuditLogEntry) -> AuditRowView:
    """Convert one :class:`AuditLogEntry` into the template-friendly view."""
    pretty = json.dumps(entry.payload, default=str, sort_keys=True)
    truncated = len(pretty) > _PAYLOAD_SNIPPET_CHARS
    snippet = pretty if not truncated else pretty[:_PAYLOAD_SNIPPET_CHARS].rstrip() + "…"
    return AuditRowView(
        id=entry.id,
        ts=entry.ts,
        actor=entry.actor,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        payload_pretty=pretty,
        payload_snippet=snippet,
        payload_truncated=truncated,
        severity=_action_severity(entry.action),
    )


def _audit_verify_defaults(hours: int) -> tuple[str, str]:
    """Default ``from`` / ``to`` values for the verify form (UTC, minute resolution)."""
    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    fmt = "%Y-%m-%dT%H:%M"
    return start.strftime(fmt), now.strftime(fmt)


_DOUGHNUT_PALETTE: tuple[str, ...] = (
    "#4f46e5",  # indigo-600
    "#16a34a",  # green-600
    "#f59e0b",  # amber-500
    "#dc2626",  # red-600
    "#0891b2",  # cyan-600
    "#a21caf",  # fuchsia-700
    "#ea580c",  # orange-600
    "#0d9488",  # teal-600
    "#7c3aed",  # violet-600
    "#65a30d",  # lime-600
)


def _recent_month_options(months_back: int) -> list[str]:
    """Return the last ``months_back`` ``YYYY-MM`` keys including the current month."""
    today = date.today()  # noqa: DTZ011 — calendar boundary
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(max(1, months_back)):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return keys


def _daily_chart_config(daily: DailyCostsResponse) -> dict[str, Any]:
    """Build a Chart.js stacked-bar config from a :class:`DailyCostsResponse`."""
    entries_asc = list(reversed(daily.entries))
    labels = [e.date.isoformat() for e in entries_asc]
    model = [float(e.model_cost_usd) for e in entries_asc]
    api = [float(e.api_cost_usd) for e in entries_asc]
    return {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "LLM (model_runs)",
                    "data": model,
                    "backgroundColor": "#4f46e5",
                    "stack": "cost",
                },
                {
                    "label": "API (vendor)",
                    "data": api,
                    "backgroundColor": "#f59e0b",
                    "stack": "cost",
                },
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {
                "x": {"stacked": True, "ticks": {"maxRotation": 60, "minRotation": 0}},
                "y": {
                    "stacked": True,
                    "beginAtZero": True,
                    "ticks": {"callback": "__USD__"},
                },
            },
            "plugins": {
                "legend": {"position": "top"},
                "tooltip": {"mode": "index", "intersect": False},
            },
        },
    }


def _agent_chart_config(by_agent: CostsByAgentResponse) -> dict[str, Any]:
    """Build a Chart.js doughnut config from a :class:`CostsByAgentResponse`."""
    agents = list(by_agent.agents)
    labels = [a.agent_id for a in agents]
    data = [float(a.cost_usd) for a in agents]
    colours = [_DOUGHNUT_PALETTE[i % len(_DOUGHNUT_PALETTE)] for i in range(len(agents))]
    return {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Cost (USD)",
                    "data": data,
                    "backgroundColor": colours,
                    "borderColor": "#0f172a",
                    "borderWidth": 1,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "legend": {"position": "bottom"},
            },
            "cutout": "55%",
        },
    }
