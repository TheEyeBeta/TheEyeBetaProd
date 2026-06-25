"""Snapshot packager visibility and build API."""

from __future__ import annotations

from uuid import UUID

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from market_control.service import MarketControlService
from rbac import MasterAdminUser, actor_from_user, require_dangerous_confirm
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    SnapshotArtifactsResponse,
    SnapshotBuildRequest,
    SnapshotBuildResponse,
    SnapshotDetailResponse,
    SnapshotListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/snapshots", tags=["snapshots"])

SNAPSHOT_CONSUMERS: tuple[str, ...] = (
    "Agent runtime (snapshot_id in run config)",
    "Backtest engine (historical packaged blobs)",
    "Proposal scoring (universe + prices bundle)",
    "Risk service (positions vs snapshot universe)",
)


def _svc(conn: DbConn, settings: SettingsDep) -> MarketControlService:
    return MarketControlService(conn, settings)


def register_snapshots_routes(limiter: Limiter) -> APIRouter:
    """Attach snapshot list, detail, artifacts, and build endpoints."""

    @router.get("", response_model=None)
    async def snapshots_page_or_list(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=30, ge=1, le=100),
    ) -> HTMLResponse | SnapshotListResponse:
        svc = _svc(conn, settings)
        listing = await svc.list_snapshots(limit=limit)
        if not prefers_html(request):
            return listing
        status_payload = await svc.get_status()
        events = await svc.recent_events(limit=30)
        failed_builds = [row for row in events if row.get("event_type") == "snapshot_build_failed"]
        latest_detail = None
        if listing.snapshots:
            try:
                latest_detail = await svc.get_snapshot(UUID(listing.snapshots[0].id))
            except ValueError:
                latest_detail = None
        log.info(
            "snapshots_page_read",
            sub=user["sub"],
            count=len(listing.snapshots),
        )
        return templates.TemplateResponse(
            request,
            "snapshots.html",
            page_context(
                request,
                user=user,
                active="snapshots",
                title="Snapshots",
                extra={
                    "listing": listing,
                    "status": status_payload,
                    "latest": latest_detail,
                    "failed_builds": failed_builds,
                    "consumers": SNAPSHOT_CONSUMERS,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.post("/build", response_model=SnapshotBuildResponse)
    @limiter.limit("5/minute")
    async def snapshots_build(
        request: Request,  # noqa: ARG001
        body: SnapshotBuildRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> SnapshotBuildResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _svc(conn, settings).build_snapshot(body, actor=actor_from_user(user))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.get("/{snapshot_id}/artifacts", response_model=SnapshotArtifactsResponse)
    async def snapshot_artifacts(
        snapshot_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> SnapshotArtifactsResponse:
        try:
            return await _svc(conn, settings).snapshot_artifacts(snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get("/{snapshot_id}", response_model=SnapshotDetailResponse)
    async def snapshot_detail(
        snapshot_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> SnapshotDetailResponse:
        try:
            return await _svc(conn, settings).get_snapshot(snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return router
