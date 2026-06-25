"""Systemd timer control plane API."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Request, status
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    actor_from_user,
    require_dangerous_confirm,
)
from slowapi import Limiter
from workers_control.service import WorkersControlService
from zinc_schemas.admin_dto import (
    TimerActionResponse,
    TimerDetailResponse,
    TimerJournalResponse,
    TimerListResponse,
    TimerSchedulePatchRequest,
)

log = structlog.get_logger()

router = APIRouter(prefix="/timers", tags=["timers"])


def _svc(conn: DbConn, settings: SettingsDep) -> WorkersControlService:
    return WorkersControlService(conn, settings)


def register_timers_routes(limiter: Limiter) -> APIRouter:
    """Attach timer control endpoints (MASTER_ADMIN for mutations)."""

    @router.get("", response_model=TimerListResponse)
    async def list_timers(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> TimerListResponse:
        payload = await _svc(conn, settings).list_timers()
        log.info("timers_listed", sub=user["sub"], count=len(payload.timers))
        return payload

    @router.get("/{name}", response_model=TimerDetailResponse)
    async def get_timer(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> TimerDetailResponse:
        detail = await _svc(conn, settings).get_timer(name)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return detail

    @router.get("/{name}/journal", response_model=TimerJournalResponse)
    async def timer_journal(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> TimerJournalResponse:
        journal = await _svc(conn, settings).timer_journal(name)
        if journal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return journal

    @router.post("/{name}/trigger", response_model=TimerActionResponse)
    @limiter.limit("10/minute")
    async def trigger_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).trigger_timer(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return result

    @router.post("/{name}/enable", response_model=TimerActionResponse)
    @limiter.limit("20/minute")
    async def enable_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).enable_timer(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return result

    @router.post("/{name}/disable", response_model=TimerActionResponse)
    @limiter.limit("10/minute")
    async def disable_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).disable_timer(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return result

    @router.post("/{name}/start", response_model=TimerActionResponse)
    @limiter.limit("20/minute")
    async def start_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).start_timer(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return result

    @router.post("/{name}/stop", response_model=TimerActionResponse)
    @limiter.limit("10/minute")
    async def stop_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).stop_timer(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return result

    @router.patch("/{name}/schedule", response_model=TimerDetailResponse)
    @limiter.limit("10/minute")
    async def patch_timer_schedule(
        request: Request,  # noqa: ARG001
        name: str,
        body: TimerSchedulePatchRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TimerDetailResponse:
        require_dangerous_confirm(body, x_confirm)
        updated = await _svc(conn, settings).patch_timer_schedule(
            name,
            body,
            actor=actor_from_user(user),
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown timer")
        return updated

    return router
