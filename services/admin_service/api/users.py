"""Admin users / RBAC API and HTML page."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from deps import DbConn, RedisOptionalDep
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    RoleChangeRequest,
    actor_from_user,
    require_dangerous_confirm,
)
from slowapi import Limiter
from users.service import AdminUsersService
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    AdminUserCreateRequest,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserRoleListResponse,
    AdminUserRolesChangeResponse,
    AdminUserSessionListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/users", tags=["users"])


class MfaConfirmRequest(BaseModel):
    """Body for confirming a pending TOTP enrollment with one code."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=8)


def _svc(conn: DbConn, redis: RedisOptionalDep) -> AdminUsersService:
    return AdminUsersService(conn, redis=redis)


def register_users_routes(limiter: Limiter) -> APIRouter:
    """Attach user control plane routes."""

    @router.get("", response_model=None)
    async def list_users_or_page(
        request: Request,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> HTMLResponse | AdminUserListResponse:
        svc = _svc(conn, redis)
        payload = await svc.list_users()
        if not prefers_html(request):
            return payload
        return templates.TemplateResponse(
            request,
            "users.html",
            page_context(
                request,
                user=user,
                active="users",
                title="Users/Permissions",
                extra={"users": payload.users},
            ),
        )

    @router.get("/{user_id}", response_model=AdminUserDetailResponse)
    async def get_user(
        user_id: UUID,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserDetailResponse:
        return await _svc(conn, redis).get_user(user_id)

    @router.post("", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def create_user(
        request: Request,
        body: AdminUserCreateRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserDetailResponse:
        result = await _svc(conn, redis).create_user(body, actor=actor_from_user(user))
        log.info("admin_user_created", sub=user["sub"], username=body.username)
        return result

    @router.patch("/{user_id}", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def patch_user(
        request: Request,
        user_id: UUID,
        body: AdminUserPatchRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserDetailResponse:
        return await _svc(conn, redis).patch_user(
            user_id,
            body,
            actor=actor_from_user(user),
        )

    @router.post("/{user_id}/disable", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def disable_user(
        request: Request,
        user_id: UUID,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserDetailResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, redis).disable_user(
            user_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/{user_id}/enable", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def enable_user(
        request: Request,
        user_id: UUID,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserDetailResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, redis).enable_user(
            user_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.get("/{user_id}/roles", response_model=AdminUserRoleListResponse)
    async def list_user_roles(
        user_id: UUID,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserRoleListResponse:
        return await _svc(conn, redis).list_roles(user_id)

    @router.post("/{user_id}/roles", response_model=AdminUserRolesChangeResponse)
    @limiter.limit("20/minute")
    async def grant_user_role(
        request: Request,
        user_id: UUID,
        body: RoleChangeRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserRolesChangeResponse:
        require_dangerous_confirm(body, x_confirm)
        if body.role == "MASTER_ADMIN" and "MASTER_ADMIN" not in (user.get("roles") or []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MASTER_ADMIN required")
        return await _svc(conn, redis).grant_role(
            user_id,
            role=body.role,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.delete("/{user_id}/roles/{role}", response_model=AdminUserRolesChangeResponse)
    @limiter.limit("20/minute")
    async def revoke_user_role(
        request: Request,
        user_id: UUID,
        role: str,
        body: RoleChangeRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserRolesChangeResponse:
        require_dangerous_confirm(body, x_confirm)
        if body.role != role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Body role must match path role",
            )
        if role == "MASTER_ADMIN" and "MASTER_ADMIN" not in (user.get("roles") or []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MASTER_ADMIN required")
        return await _svc(conn, redis).revoke_role(
            user_id,
            role=role,
            actor=actor_from_user(user),
            reason=body.reason,
            allow_final_master_removal=body.allow_final_master_removal,
        )

    @router.get("/{user_id}/sessions", response_model=AdminUserSessionListResponse)
    async def list_user_sessions(
        user_id: UUID,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserSessionListResponse:
        return await _svc(conn, redis).list_sessions(user_id)

    @router.post("/{user_id}/sessions/revoke", response_model=AdminUserSessionListResponse)
    @limiter.limit("20/minute")
    async def revoke_all_sessions(
        request: Request,
        user_id: UUID,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserSessionListResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, redis).revoke_all_sessions(
            user_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/{user_id}/mfa/reset", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def reset_user_mfa(
        request: Request,
        user_id: UUID,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> AdminUserDetailResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, redis).reset_mfa(
            user_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/{user_id}/mfa/enroll")
    @limiter.limit("20/minute")
    async def enroll_user_mfa(
        request: Request,
        user_id: UUID,
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
        x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
    ) -> dict[str, str]:
        """Generate a pending TOTP secret for the operator to enroll in an authenticator app."""
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, redis).enroll_mfa(
            user_id,
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/{user_id}/mfa/confirm", response_model=AdminUserDetailResponse)
    @limiter.limit("20/minute")
    async def confirm_user_mfa(
        request: Request,
        user_id: UUID,
        body: MfaConfirmRequest,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> AdminUserDetailResponse:
        """Verify the pending TOTP secret with one code and enable MFA."""
        return await _svc(conn, redis).confirm_mfa(
            user_id,
            code=body.code,
            actor=actor_from_user(user),
        )

    @router.get("/fragments/{user_id}", response_class=HTMLResponse, include_in_schema=False)
    async def user_detail_fragment(
        request: Request,
        user_id: UUID,
        user: MasterAdminUser,
        conn: DbConn,
        redis: RedisOptionalDep,
    ) -> HTMLResponse:
        detail = await _svc(conn, redis).get_user(user_id)
        sessions = await _svc(conn, redis).list_sessions(user_id)
        return templates.TemplateResponse(
            request,
            "components/_user_detail_panel.html",
            {
                "request": request,
                "detail": detail,
                "sessions": sessions.sessions,
            },
        )

    return router
