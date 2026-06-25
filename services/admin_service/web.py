"""Frontend wiring for admin-service: Jinja2 templates, static assets, layout shell.

Templates, static assets, and ``frontend_ia`` live in the sibling
``TheEyeBetaAdminFrontend`` repository. This module resolves those paths and
mounts them for FastAPI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from frontend_paths import (
    ensure_frontend_on_path,
    resolve_frontend_root,
    static_dir,
    templates_dir,
    terminal_dir,
)
from settings import get_settings

_FRONTEND_ROOT = ensure_frontend_on_path(
    resolve_frontend_root(get_settings().admin_frontend_root),
)

from auth import get_current_user
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from frontend_ia.modules import REQUIRED_MODULE_KEYS, TERMINAL_MODULES, module_by_key
from frontend_ia.nav import build_nav_groups, build_nav_items, normalize_user_roles
from frontend_ia.shell import build_module_shell_context
from markupsafe import Markup

if TYPE_CHECKING:
    from fastapi import FastAPI

TEMPLATES_DIR = templates_dir(_FRONTEND_ROOT)
STATIC_DIR = static_dir(_FRONTEND_ROOT)
TERMINAL_DIR = terminal_dir(_FRONTEND_ROOT)

STATIC_URL_PREFIX = "/admin/static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

templates.env.globals["static_url"] = STATIC_URL_PREFIX
templates.env.globals["terminal_module_count"] = len(TERMINAL_MODULES)


def _jinja_tojson(value: object, indent: int = 0) -> Markup:
    import json

    from pydantic import BaseModel

    def _default(obj: object) -> object:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        return str(obj)

    # Mark the JSON string safe so Jinja's autoescaper doesn't HTML-entity
    # escape the quotes (e.g. `"` -> `&#34;`), which breaks JSON.parse() on
    # anything embedded via this filter. Safe here: the content is our own
    # json.dumps() output, not unescaped user input.
    return Markup(json.dumps(value, indent=indent or None, default=_default))  # noqa: S704


templates.env.filters["tojson"] = _jinja_tojson

NAV_ITEMS: list[dict[str, str]] = build_nav_items(["operator", "MASTER_ADMIN"])

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
    user: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the base Jinja2 context shared by every page template."""
    roles = normalize_user_roles(user)
    nav_groups = build_nav_groups(roles)
    from_group = request.query_params.get("from_group")
    scoped_nav_groups = nav_groups
    if from_group:
        matched = [g for g in nav_groups if str(g["name"]).lower() == from_group.lower()]
        if matched:
            scoped_nav_groups = matched
    context: dict[str, object] = {
        "request": request,
        "nav_items": build_nav_items(roles),
        "nav_groups": scoped_nav_groups,
        "nav_scoped_to_group": from_group if scoped_nav_groups is not nav_groups else None,
        "active_nav": active,
        "page_title": title or "Admin",
        "static_url": STATIC_URL_PREFIX,
        "user_roles": roles,
        "is_master_admin": "MASTER_ADMIN" in roles,
    }
    if active:
        module = module_by_key(active)
        if module is not None:
            context.update(build_module_shell_context(module))
    if extra:
        context.update(extra)
    return context


def prefers_html(request: Request) -> bool:
    """Return True for admin UI navigation, False for explicit JSON API clients."""
    accept = request.headers.get("accept", "").lower()
    if request.headers.get("hx-request", "").lower() == "true":
        return True
    if "application/json" in accept and "text/html" not in accept:
        return False
    return True


def register_web_routes() -> APIRouter:
    """Attach layout-check and other shell-only routes to ``router``."""

    @router.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:
        """Operator login — stores access JWT in sessionStorage via app.js."""
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "page_title": "Sign in",
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
        user: dict[str, str] = Depends(get_current_user),
    ) -> HTMLResponse:
        """Render the layout-shell acceptance page (auth-gated like the rest of /admin)."""
        return templates.TemplateResponse(
            request,
            "pages/_layout_check.html",
            page_context(
                request,
                active="command-center",
                title="Layout check",
                user=user,
            ),
        )

    return router


__all__ = [
    "NAV_ITEMS",
    "REQUIRED_MODULE_KEYS",
    "STATIC_URL_PREFIX",
    "mount_static",
    "page_context",
    "prefers_html",
    "register_web_routes",
    "router",
    "templates",
]
