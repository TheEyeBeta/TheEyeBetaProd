"""Frontend wiring for admin-service: Jinja2 templates, static assets, layout shell.

The admin UI is server-rendered Jinja2 + htmx + Tailwind/Chart.js via CDN.
This module owns the lookup paths so every page handler (P-FE-01 onward) can
``from web import templates`` and call ``templates.TemplateResponse(...)``.

The layout-check route mounted here renders ``pages/_layout_check.html`` —
it exists so the acceptance test for P-FE-00 can assert the shell renders
correctly without depending on any production page templates.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from auth import get_current_user
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from fastapi import FastAPI

_SERVICE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _SERVICE_DIR / "templates"
STATIC_DIR = _SERVICE_DIR / "static"

# Static URL prefix — matches how main.py mounts the StaticFiles app.
STATIC_URL_PREFIX = "/admin/static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_url"] = STATIC_URL_PREFIX

#: Sidebar/top-nav entries shown on every page. Update here when a new page
#: ships under a future ``P-FE-*`` ticket so the layout stays in sync.
NAV_ITEMS: list[dict[str, str]] = [
    {"label": "Dashboard", "href": "/admin/", "key": "dashboard"},
    {"label": "Orders", "href": "/admin/orders", "key": "orders"},
    {"label": "Audit", "href": "/admin/audit", "key": "audit"},
    {"label": "Agents", "href": "/admin/agents", "key": "agents"},
    {"label": "Briefings", "href": "/admin/briefings", "key": "briefings"},
    {"label": "Violations", "href": "/admin/violations", "key": "violations"},
    {"label": "Costs", "href": "/admin/costs", "key": "costs"},
    {"label": "SQL", "href": "/admin/sql", "key": "sql"},
    {"label": "Proposals", "href": "/admin/proposals", "key": "proposals"},
]

router = APIRouter(tags=["web"])


def mount_static(app: FastAPI) -> None:
    """Mount ``static/`` under ``/admin/static`` for templates to reference."""
    app.mount(
        STATIC_URL_PREFIX,
        StaticFiles(directory=str(STATIC_DIR)),
        name="admin-static",
    )


def page_context(
    request: Request,
    *,
    active: str | None = None,
    title: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the base Jinja2 context shared by every page template.

    Args:
        request: Active FastAPI request (required by Jinja2Templates).
        active: ``NAV_ITEMS[*].key`` to mark as the current page.
        title: ``<title>`` override; defaults to ``"Admin"``.
        extra: Additional template variables to merge in.

    Returns:
        Context dict suitable for ``templates.TemplateResponse``.
    """
    context: dict[str, object] = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_nav": active,
        "page_title": title or "Admin",
        "static_url": STATIC_URL_PREFIX,
    }
    if extra:
        context.update(extra)
    return context


def register_web_routes() -> APIRouter:
    """Attach layout-check, login, and other shell-only routes to ``router``."""

    @router.get(
        "/login",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def login_page(request: Request) -> HTMLResponse:
        """Render the operator login page (unauthenticated)."""
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "static_url": STATIC_URL_PREFIX,
            },
        )

    @router.get(
        "/_layout-check",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def layout_check(
        request: Request,
        _user: dict[str, str] = Depends(get_current_user),
    ) -> HTMLResponse:
        """Render the layout-shell acceptance page (auth-gated like the rest of /admin)."""
        return templates.TemplateResponse(
            request,
            "pages/_layout_check.html",
            page_context(request, active="dashboard", title="Layout check"),
        )

    return router
