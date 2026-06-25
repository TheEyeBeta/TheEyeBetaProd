"""Module page shells — routes for Terminal IA modules without full UI yet."""

from __future__ import annotations

import json

import structlog
from auth import CurrentUser
from deps import SettingsDep
from dataapi_control.client import DataApiBridge, fetch_dataapi_health
from edge.service import EdgeRegistryService
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from frontend_ia.modules import module_by_key
from frontend_ia.shell import build_module_shell_context
from web import page_context, templates

log = structlog.get_logger()

router = APIRouter(tags=["module-views"])

SHELL_MODULE_KEYS: tuple[str, ...] = (
    "integrations",
    "observability",
    "universe-screener",
)


def register_module_views() -> APIRouter:
    """HTML routes for Terminal module shells."""

    def _shell_response(
        request: Request,
        user: CurrentUser,
        module_key: str,
        *,
        extra: dict[str, object] | None = None,
    ) -> HTMLResponse:
        module = module_by_key(module_key)
        if module is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module")
        ctx = build_module_shell_context(module)
        payload = page_context(
            request,
            active=module_key,
            title=module.title,
            user=user,
            extra={**ctx, **(extra or {})},
        )
        return templates.TemplateResponse(request, "module_shell.html", payload)

    for key in SHELL_MODULE_KEYS:
        mod = module_by_key(key)
        if mod is None:
            continue
        route_path = mod.href.removeprefix("/admin")

        def _make_handler(module_key: str = key, path: str = route_path):
            @router.get(path, response_class=HTMLResponse, include_in_schema=False)
            async def _module_shell_page(
                request: Request,
                user: CurrentUser,
            ) -> HTMLResponse:
                return _shell_response(request, user, module_key)

            return _module_shell_page

        _make_handler()

    @router.get("/edge/routes", response_class=HTMLResponse, include_in_schema=False)
    async def edge_routes_page(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> HTMLResponse:
        svc = EdgeRegistryService(settings)
        routes = await svc.list_routes()
        drift = svc.drift_report_for_routes(routes.routes)
        trusted = await svc.trusted_hosts()
        module = module_by_key("edge-routes")
        assert module is not None
        ctx = build_module_shell_context(module)
        return templates.TemplateResponse(
            request,
            "edge_routes.html",
            page_context(
                request,
                active="edge-routes",
                title="Edge Routes",
                user=user,
                extra={
                    **ctx,
                    "routes": routes,
                    "drift": drift,
                    "trusted": trusted,
                },
            ),
        )

    @router.get("/data-api", response_class=HTMLResponse, include_in_schema=False)
    async def data_api_page(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> HTMLResponse:
        svc = EdgeRegistryService(settings)
        routes = await svc.list_routes()
        drift = svc.drift_report_for_routes(routes.routes)
        trusted = await svc.trusted_hosts()
        dataapi_rows = [r for r in routes.routes if r.expected_service_name == "data-api"]
        bridge_health: dict[str, object] = {"status": "unconfigured", "reachable": False}
        if settings.dataapi_credentials_present():
            try:
                bridge_health = await fetch_dataapi_health(settings)
            except Exception as exc:  # noqa: BLE001 — surface probe errors in UI
                bridge_health = {
                    "status": "error",
                    "reachable": False,
                    "detail": str(exc)[:200],
                    "base_url": settings.dataapi_bridge_base_url(),
                }
        module = module_by_key("data-api")
        assert module is not None
        ctx = build_module_shell_context(module)
        details = {
            "service": "Data API",
            "port": 7000,
            "systemd_unit": "theeyebeta-dataapi.service",
            "health_endpoint": "/health",
            "hostnames": [r.hostname for r in dataapi_rows],
            "routes": [r.model_dump(mode="json") for r in dataapi_rows],
            "shared_backend_warning": routes.shared_backend_warning,
            "trusted_hosts": trusted.model_dump(mode="json"),
            "drift_alerts": drift.alerts,
        }
        return templates.TemplateResponse(
            request,
            "data_api.html",
            page_context(
                request,
                active="data-api",
                title="Data API",
                user=user,
                extra={
                    **ctx,
                    "dataapi_rows": dataapi_rows,
                    "details_json": json.dumps(details, indent=2, default=str),
                    "shared_backend_warning": routes.shared_backend_warning,
                    "drift": drift,
                    "trusted": trusted,
                    "bridge_health": bridge_health,
                    "dataapi_bridge_configured": settings.dataapi_credentials_present(),
                },
            ),
        )

    return router
