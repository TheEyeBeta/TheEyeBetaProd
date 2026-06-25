"""Allowlisted command console API and CLI page."""

from __future__ import annotations

from uuid import UUID

import structlog
from auth import CurrentUser
from command_control.service import CommandControlService
from deps import DbConn, NatsClient, RedisOptionalDep, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from rbac import DangerousActionRequest, require_dangerous_confirm
from slowapi import Limiter
from web import page_context, templates
from zinc_schemas.admin_dto import (
    CommandListResponse,
    CommandPreviewRequest,
    CommandPreviewResponse,
    CommandRunDetailResponse,
    CommandRunRequest,
    CommandRunResponse,
    CommandRunsListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/commands", tags=["commands"])
console_router = APIRouter(tags=["console"])


def _svc(
    conn: DbConn,
    settings: SettingsDep,
    redis: RedisOptionalDep,
    nats: NatsClient,
) -> CommandControlService:
    return CommandControlService(conn, settings, redis=redis, nats=nats)


def register_commands_routes(limiter: Limiter) -> APIRouter:
    """Attach command registry, preview, run, and history endpoints."""

    @router.get("", response_model=CommandListResponse)
    async def list_commands(user: CurrentUser) -> CommandListResponse:
        return CommandControlService.list_commands()

    @router.post("/preview", response_model=CommandPreviewResponse)
    @limiter.limit("60/minute")
    async def preview_command(
        request: Request,  # noqa: ARG001
        body: CommandPreviewRequest,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        nats: NatsClient,
    ) -> CommandPreviewResponse:
        return await _svc(conn, settings, redis, nats).preview(body, user=user)

    @router.post("/run", response_model=CommandRunResponse)
    @limiter.limit("30/minute")
    async def run_command(
        request: Request,  # noqa: ARG001
        body: CommandRunRequest,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        nats: NatsClient,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> CommandRunResponse:
        from command_control.parser import parse_command

        try:
            parsed = parse_command(body.command)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

        if parsed.definition.confirmation_required:
            require_dangerous_confirm(
                DangerousActionRequest(reason=body.reason or "", confirm=body.confirm),
                x_confirm,
            )

        try:
            return await _svc(conn, settings, redis, nats).run(body, user=user)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.get("/runs", response_model=CommandRunsListResponse)
    async def list_command_runs(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        nats: NatsClient,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> CommandRunsListResponse:
        return await _svc(conn, settings, redis, nats).list_runs(limit=limit)

    @router.get("/runs/{run_id}", response_model=CommandRunDetailResponse)
    async def get_command_run(
        run_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        nats: NatsClient,
    ) -> CommandRunDetailResponse:
        try:
            return await _svc(conn, settings, redis, nats).get_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @console_router.get("/console", response_class=HTMLResponse, include_in_schema=False)
    async def command_console_page(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        nats: NatsClient,
    ) -> HTMLResponse:
        listing = CommandControlService.list_commands()
        history = await _svc(conn, settings, redis, nats).list_runs(limit=30)
        return templates.TemplateResponse(
            request,
            "console.html",
            page_context(
                request,
                user=user,
                active="console",
                title="Command Console",
                extra={
                    "commands": listing.commands,
                    "history": history.runs,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    return router
