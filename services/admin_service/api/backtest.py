"""Admin backtest API — proxy to backtest-engine + recent-runs listing."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import httpx
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, Query, Request, status
from rbac import Role, require_role
from settings import Settings
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    BacktestListResponse,
    BacktestResultsResponse,
    BacktestRunSummary,
    StartBacktestRequest,
    StartBacktestResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/backtest", tags=["backtest"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_ENGINE_TIMEOUT_SECONDS = 60.0


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


def _row_to_summary(row: asyncpg.Record) -> BacktestRunSummary:
    """Map a DB row to :class:`BacktestRunSummary`."""
    return BacktestRunSummary(
        id=row["id"],
        strategy_id=row["strategy_id"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        universe=row["universe"],
        git_sha=row["git_sha"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        status=row["status"],
        result_blob_uri=row["result_blob_uri"],
    )


def _engine_url(settings: Settings, suffix: str) -> str:
    """Build a backtest-engine URL with consistent stripping."""
    return f"{settings.backtest_engine_url.rstrip('/')}{suffix}"


def _raise_for_engine_status(response: httpx.Response) -> None:
    """Translate backtest-engine HTTP errors into admin-side HTTPException."""
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=response.text)
    if response.status_code == status.HTTP_409_CONFLICT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=response.text)
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=response.text,
        )
    if response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=response.text,
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="backtest-engine returned 5xx",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(status_code=response.status_code, detail=response.text)


def register_backtest_routes(limiter: Limiter) -> APIRouter:
    """Attach backtest handlers (POST is rate-limited)."""

    @router.get("", response_model=BacktestListResponse)
    async def list_recent_backtests(
        user: CurrentUser,
        conn: DbConn,
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    ) -> BacktestListResponse:
        """List recent backtest runs (newest first)."""
        rows = await conn.fetch(
            """
            SELECT id, strategy_id, start_date, end_date, universe, git_sha,
                   started_at, ended_at, status, result_blob_uri
              FROM theeyebeta.backtest_runs
             ORDER BY started_at DESC
             LIMIT $1
            """,
            limit,
        )
        runs = [_row_to_summary(row) for row in rows]
        log.info(
            "admin_backtest_list",
            count=len(runs),
            sub=user["sub"],
        )
        return BacktestListResponse(runs=runs, limit=limit)

    @router.post("", response_model=StartBacktestResponse)
    @limiter.limit("20/minute")
    async def start_backtest(
        request: Request,  # noqa: ARG001 — required by slowapi
        body: StartBacktestRequest,
        conn: DbConn,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.ANALYST),
    ) -> StartBacktestResponse:
        """Forward to ``backtest-engine POST /backtest/run`` and audit log."""
        if body.start_date > body.end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="start_date must be <= end_date",
            )

        actor = _actor(user)
        audit_payload = body.model_dump(mode="json")

        engine_payload = body.model_dump(mode="json", exclude_none=True)
        url = _engine_url(settings, "/backtest/run")
        try:
            async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=engine_payload)
        except httpx.HTTPError as exc:
            log.error("backtest_engine_unreachable", url=url, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="backtest-engine is unreachable",
            ) from exc

        _raise_for_engine_status(response)

        data: dict[str, Any] = response.json()
        run_id = str(data.get("backtest_run_id") or "")
        if not run_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="backtest-engine response missing backtest_run_id",
            )

        await write_audit_log(
            conn,
            actor=actor,
            action="start.backtest",
            entity_type="backtest_run",
            entity_id=run_id,
            payload={**audit_payload, "backtest_run_id": run_id},
        )

        log.info(
            "admin_backtest_started",
            backtest_run_id=run_id,
            strategy_id=body.strategy_id,
            sub=user["sub"],
        )
        return StartBacktestResponse(**data)

    @router.get("/{backtest_id}/results", response_model=BacktestResultsResponse)
    async def get_backtest_results(
        backtest_id: UUID,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> BacktestResultsResponse:
        """Proxy ``backtest-engine GET /backtest/{id}/results``."""
        url = _engine_url(settings, f"/backtest/{backtest_id}/results")
        try:
            async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            log.error("backtest_engine_results_unreachable", url=url, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="backtest-engine is unreachable",
            ) from exc

        _raise_for_engine_status(response)

        data: dict[str, Any] = response.json()
        log.info(
            "admin_backtest_results_fetched",
            backtest_run_id=str(backtest_id),
            status=data.get("status"),
            sub=user["sub"],
        )
        return BacktestResultsResponse(
            backtest_run_id=backtest_id,
            status=str(data.get("status", "")),
            metrics=data.get("metrics", {}) or {},
            result_blob_uri=data.get("result_blob_uri"),
        )

    return router
