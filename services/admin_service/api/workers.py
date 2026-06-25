"""Workers control plane API and HTML page."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    actor_from_user,
    require_dangerous_confirm,
)
from slowapi import Limiter
from web import page_context, prefers_html, templates
from workers_control.service import WorkersControlService
from zinc_schemas.admin_dto import (
    WorkerActionResponse,
    WorkerConfigPatchRequest,
    WorkerConfigResponse,
    WorkerDetailResponse,
    WorkerListResponse,
    WorkerLogsResponse,
    WorkerRunListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/workers", tags=["workers"])


def _svc(conn: DbConn, settings: SettingsDep) -> WorkersControlService:
    return WorkersControlService(conn, settings)


def register_workers_routes(limiter: Limiter) -> APIRouter:
    """Attach worker registry and control endpoints."""

    @router.get("", response_model=None)
    async def list_workers_or_page(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse | WorkerListResponse:
        payload = await _svc(conn, settings).list_workers()
        log.info("workers_listed", sub=user["sub"], count=len(payload.workers))
        if not prefers_html(request):
            return payload
        return templates.TemplateResponse(
            request,
            "workers.html",
            page_context(
                request,
                user=user,
                active="workers",
                title="Workers/Schedulers",
                extra={
                    "registry": payload,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.get("/fragments/{name}", response_class=HTMLResponse, include_in_schema=False)
    async def worker_detail_fragment(
        request: Request,
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        detail = await _svc(conn, settings).get_worker(name)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return templates.TemplateResponse(
            request,
            "components/_worker_detail.html",
            {
                "request": request,
                "worker": detail,
                "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
            },
        )

    @router.get("/{name}", response_model=WorkerDetailResponse)
    async def get_worker(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> WorkerDetailResponse:
        detail = await _svc(conn, settings).get_worker(name)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return detail

    @router.get("/{name}/runs", response_model=WorkerRunListResponse)
    async def list_worker_runs(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> WorkerRunListResponse:
        runs = await _svc(conn, settings).list_runs(name)
        if runs is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return runs

    @router.get("/{name}/config", response_model=WorkerConfigResponse)
    async def get_worker_config(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> WorkerConfigResponse:
        config = await _svc(conn, settings).get_config(name)
        if config is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return config

    @router.get("/{name}/logs", response_model=WorkerLogsResponse)
    async def get_worker_logs(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> WorkerLogsResponse:
        logs = await _svc(conn, settings).get_logs(name)
        if logs is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return logs

    @router.post("/{name}/run", response_model=WorkerActionResponse)
    @limiter.limit("10/minute")
    async def run_worker(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).force_run(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return result

    @router.post("/{name}/stop", response_model=WorkerActionResponse)
    @limiter.limit("10/minute")
    async def stop_worker(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).stop_worker(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return result

    @router.post("/{name}/pause", response_model=WorkerActionResponse)
    @limiter.limit("20/minute")
    async def pause_worker(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).pause_worker(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return result

    @router.post("/{name}/resume", response_model=WorkerActionResponse)
    @limiter.limit("20/minute")
    async def resume_worker(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).resume_worker(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return result

    @router.post("/{name}/retry/{run_id}", response_model=WorkerActionResponse)
    @limiter.limit("10/minute")
    async def retry_worker_run(
        request: Request,  # noqa: ARG001
        name: str,
        run_id: int,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerActionResponse:
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).retry_run(
            name,
            run_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker or run")
        return result

    @router.patch("/{name}/config", response_model=WorkerConfigResponse)
    @limiter.limit("10/minute")
    async def patch_worker_config(
        request: Request,  # noqa: ARG001
        name: str,
        body: WorkerConfigPatchRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> WorkerConfigResponse:
        require_dangerous_confirm(body, x_confirm)
        updated = await _svc(conn, settings).patch_config(
            name,
            body,
            actor=actor_from_user(user),
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown worker")
        return updated

    return router
