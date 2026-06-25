"""Admin services API — allowlisted systemd control plane."""

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
from services_control.registry import is_critical_service, service_by_key
from services_control.service import ServicesControlService
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    ServiceActionRequest,
    ServiceActionResponse,
    ServiceDetailResponse,
    ServiceHistoryResponse,
    ServiceListResponse,
    ServiceLogsResponse,
    ServicePortRegistryResponse,
    ServiceStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/services", tags=["services"])


def _svc(conn: DbConn, settings: SettingsDep) -> ServicesControlService:
    return ServicesControlService(conn, settings)


def _reject_unknown(name: str) -> None:
    if service_by_key(name) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")


def register_services_routes(limiter: Limiter) -> APIRouter:
    """Attach allowlisted systemd status and mutation handlers."""

    @router.get("", response_model=None)
    async def list_services_or_page(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse | ServiceListResponse:
        payload = await _svc(conn, settings).list_services()
        log.info("services_listed", sub=user["sub"], count=len(payload.services))
        if not prefers_html(request):
            return payload
        return templates.TemplateResponse(
            request,
            "services.html",
            page_context(
                request,
                user=user,
                active="services",
                title="Services/systemd",
                extra={
                    "registry": payload,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.get("/ports", response_model=ServicePortRegistryResponse)
    async def service_port_registry(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServicePortRegistryResponse:
        return await _svc(conn, settings).port_registry()

    @router.get("/status", response_model=ServiceStatusResponse)
    async def list_service_status_legacy(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceStatusResponse:
        """Legacy JSON shape for existing integrations."""
        return await _svc(conn, settings).legacy_status_response()

    @router.get("/fragments/{name}", response_class=HTMLResponse, include_in_schema=False)
    async def service_detail_fragment(
        request: Request,
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse:
        _reject_unknown(name)
        detail = await _svc(conn, settings).get_service(name)
        assert detail is not None
        return templates.TemplateResponse(
            request,
            "components/_service_detail.html",
            {
                "request": request,
                "service": detail,
                "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
            },
        )

    @router.get("/{name}", response_model=ServiceDetailResponse)
    async def get_service(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceDetailResponse:
        detail = await _svc(conn, settings).get_service(name)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return detail

    @router.get("/{name}/logs", response_model=ServiceLogsResponse)
    async def get_service_logs(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceLogsResponse:
        logs = await _svc(conn, settings).get_logs(name)
        if logs is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return logs

    @router.get("/{name}/history", response_model=ServiceHistoryResponse)
    async def get_service_history(
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceHistoryResponse:
        history = await _svc(conn, settings).get_history(name)
        if history is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return history

    @router.post("/{name}/restart", response_model=ServiceActionResponse)
    @limiter.limit("20/minute")
    async def restart_service(
        request: Request,  # noqa: ARG001
        name: str,
        body: ServiceActionRequest,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceActionResponse:
        _reject_unknown(name)
        service = service_by_key(name)
        assert service is not None
        if not service.supports_restart:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Restart not supported for this service",
            )
        result = await _svc(conn, settings).restart(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        assert result is not None
        return result

    @router.post("/{name}/start", response_model=ServiceActionResponse)
    @limiter.limit("20/minute")
    async def start_service(
        request: Request,  # noqa: ARG001
        name: str,
        body: ServiceActionRequest,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceActionResponse:
        _reject_unknown(name)
        result = await _svc(conn, settings).start(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return result

    @router.post("/{name}/stop", response_model=ServiceActionResponse)
    @limiter.limit("10/minute")
    async def stop_service(
        request: Request,
        name: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceActionResponse:
        _reject_unknown(name)
        payload = await request.json()
        if is_critical_service(name):
            roles = user.get("roles") or []
            if "MASTER_ADMIN" not in roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Critical service stop requires MASTER_ADMIN",
                )
            body = DangerousActionRequest.model_validate(payload)
            require_dangerous_confirm(body, request.headers.get("X-Confirm"))
            reason = body.reason
        else:
            body = ServiceActionRequest.model_validate(payload)
            reason = body.reason
        result = await _svc(conn, settings).stop(
            name,
            actor=actor_from_user(user),
            reason=reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return result

    @router.post("/{name}/enable", response_model=ServiceActionResponse)
    @limiter.limit("20/minute")
    async def enable_service(
        request: Request,  # noqa: ARG001
        name: str,
        body: ServiceActionRequest,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ServiceActionResponse:
        _reject_unknown(name)
        result = await _svc(conn, settings).enable(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return result

    @router.post("/{name}/disable", response_model=ServiceActionResponse)
    @limiter.limit("10/minute")
    async def disable_service(
        request: Request,  # noqa: ARG001
        name: str,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ServiceActionResponse:
        _reject_unknown(name)
        require_dangerous_confirm(body, x_confirm)
        result = await _svc(conn, settings).disable(
            name,
            actor=actor_from_user(user),
            reason=body.reason,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown service")
        return result

    return router
