"""Backtests control plane — plural routes per Prompt 14."""

from __future__ import annotations

from uuid import UUID

import structlog
from api.backtest import (
    _DEFAULT_LIMIT,
    _MAX_LIMIT,
    _actor,
    _engine_url,
    _raise_for_engine_status,
    _row_to_summary,
)
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from rbac import MasterAdminUser, require_dangerous_confirm
from settings import Settings
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    BacktestArtifactsResponse,
    BacktestCancelRequest,
    BacktestCancelResponse,
    BacktestDetailResponse,
    BacktestListResponse,
    BacktestRetryRequest,
    BacktestRetryResponse,
    BacktestResultsResponse,
    StartBacktestDangerousRequest,
    StartBacktestResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _intel(conn: DbConn, settings: SettingsDep):
    from intelligence_control.service import IntelligenceControlService

    return IntelligenceControlService(conn, settings)


def register_backtests_routes(limiter: Limiter) -> APIRouter:
    """Attach backtest visibility and control endpoints at ``/admin/backtests``."""

    @router.get("", response_model=None)
    async def backtests_page_or_list(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    ) -> BacktestListResponse | HTMLResponse:
        rows = await conn.fetch(
            """
            SELECT id, strategy_id, start_date, end_date, universe, git_sha,
                   started_at, ended_at, status, result_blob_uri
              FROM theeyebeta.backtest_runs
             ORDER BY started_at DESC NULLS LAST
             LIMIT $1
            """,
            limit,
        )
        runs = [_row_to_summary(row) for row in rows]
        listing = BacktestListResponse(runs=runs, limit=limit)
        if not prefers_html(request):
            return listing
        return templates.TemplateResponse(
            request,
            "backtests.html",
            page_context(
                request,
                user=user,
                active="backtests",
                title="Backtests",
                extra={
                    "listing": listing,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.post("", response_model=StartBacktestResponse)
    @limiter.limit("20/minute")
    async def start_backtest(
        request: Request,  # noqa: ARG001
        body: StartBacktestDangerousRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> StartBacktestResponse:
        require_dangerous_confirm(body, x_confirm)
        if body.start_date > body.end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start_date must be <= end_date",
            )
        actor = _actor(user)
        engine_payload = body.model_dump(
            mode="json",
            exclude={"reason", "confirm"},
            exclude_none=True,
        )
        url = _engine_url(settings, "/backtest/run")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=engine_payload)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="backtest-engine is unreachable",
            ) from exc
        _raise_for_engine_status(response)
        data = response.json()
        run_id = str(data.get("backtest_run_id") or "")
        await write_audit_log(
            conn,
            actor=actor,
            action="start.backtest",
            entity_type="backtest_run",
            entity_id=run_id,
            payload={**engine_payload, "reason": body.reason},
        )
        return StartBacktestResponse(**data)

    @router.get("/{backtest_id}", response_model=BacktestDetailResponse)
    async def get_backtest(
        backtest_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> BacktestDetailResponse:
        try:
            return await _intel(conn, settings).get_backtest_detail(backtest_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.post("/{backtest_id}/cancel", response_model=BacktestCancelResponse)
    @limiter.limit("10/minute")
    async def cancel_backtest(
        request: Request,  # noqa: ARG001
        backtest_id: UUID,
        body: BacktestCancelRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> BacktestCancelResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _intel(conn, settings).cancel_backtest(
                backtest_id,
                actor=f"admin-api:{user['sub']}",
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.post("/{backtest_id}/retry", response_model=BacktestRetryResponse)
    @limiter.limit("10/minute")
    async def retry_backtest(
        request: Request,  # noqa: ARG001
        backtest_id: UUID,
        body: BacktestRetryRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> BacktestRetryResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _intel(conn, settings).retry_backtest(
                backtest_id,
                actor=f"admin-api:{user['sub']}",
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.get("/{backtest_id}/artifacts", response_model=BacktestArtifactsResponse)
    async def backtest_artifacts(
        backtest_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> BacktestArtifactsResponse:
        try:
            return await _intel(conn, settings).backtest_artifacts(backtest_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get("/{backtest_id}/results", response_model=BacktestResultsResponse)
    async def get_backtest_results(
        backtest_id: UUID,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> BacktestResultsResponse:
        """Proxy ``backtest-engine GET /backtest/{id}/results``."""
        import httpx

        url = _engine_url(settings, f"/backtest/{backtest_id}/results")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="backtest-engine is unreachable",
            ) from exc
        _raise_for_engine_status(response)
        data = response.json()
        return BacktestResultsResponse(
            backtest_run_id=backtest_id,
            status=str(data.get("status", "")),
            metrics=data.get("metrics", {}) or {},
            result_blob_uri=data.get("result_blob_uri"),
        )

    return router
