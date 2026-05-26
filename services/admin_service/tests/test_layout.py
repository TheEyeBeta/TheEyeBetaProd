"""Acceptance tests for P-FE-00 — base layout, nav, modal, static assets.

These tests use a lightweight FastAPI app (no DB, NATS, or Redis) so they
run in any environment, including the Windows operator laptop where no
Docker daemon is available.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


@pytest.fixture
def layout_client() -> TestClient:
    """Build a minimal FastAPI app mounting only the web router + static."""
    from auth import get_current_user  # noqa: PLC0415
    from web import (  # noqa: PLC0415
        mount_static,
        register_web_routes,
    )
    from web import router as web_router  # noqa: PLC0415

    register_web_routes()
    app = FastAPI()
    app.include_router(web_router, prefix="/admin")
    mount_static(app)

    async def _fake_user() -> dict[str, str]:
        return {"sub": "test"}

    app.dependency_overrides[get_current_user] = _fake_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_layout_check_renders_200(layout_client: TestClient) -> None:
    """The acceptance page returns 200 with HTML body."""
    response = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text.lower()


def test_layout_includes_required_cdn_scripts(layout_client: TestClient) -> None:
    """Tailwind, htmx (pinned 2.x), and Chart.js are loaded from CDN."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    assert "cdn.tailwindcss.com/3.4.10" in body
    assert "unpkg.com/htmx.org@2.0.3" in body
    assert "cdn.jsdelivr.net/npm/chart.js@4.4.6" in body


def test_layout_includes_local_static_assets(layout_client: TestClient) -> None:
    """The shell links to the local style sheet and the shell JS module."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    assert "/admin/static/style.css" in body
    assert "/admin/static/js/app.js" in body
    assert "/admin/static/js/tailwind-config.js" in body


def test_nav_contains_all_required_links(layout_client: TestClient) -> None:
    """Every top-nav link listed in P-FE-00 is rendered with the right href."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    expected = [
        ("Dashboard", '/admin/"'),
        ("Orders", '/admin/orders"'),
        ("Audit", '/admin/audit"'),
        ("Agents", '/admin/agents"'),
        ("Violations", '/admin/violations"'),
        ("Costs", '/admin/costs"'),
        ("SQL", '/admin/sql"'),
        ("Proposals", '/admin/proposals"'),
    ]
    for label, href_suffix in expected:
        assert label in body, f"nav label {label!r} missing"
        assert href_suffix in body, f"nav href for {label!r} missing"
    # Logout button hits the auth router; htmx attribute drives it.
    assert 'hx-post="/admin/auth/logout"' in body


def test_layout_marks_active_nav(layout_client: TestClient) -> None:
    """``active_nav='dashboard'`` is applied to the Dashboard link only."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    # The active link carries aria-current="page".
    assert 'aria-current="page"' in body
    # And only one nav item should be marked as active.
    assert body.count('aria-current="page"') == 1


def test_modal_container_present(layout_client: TestClient) -> None:
    """The htmx modal target #modal is included on every page."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    assert 'id="modal"' in body
    assert 'role="dialog"' in body
    assert 'aria-modal="true"' in body


def test_theme_toggle_present(layout_client: TestClient) -> None:
    """The dark-mode toggle button is wired to the shell JS."""
    body = layout_client.get(
        "/admin/_layout-check",
        headers={"Authorization": "Bearer test"},
    ).text
    assert 'id="theme-toggle"' in body
    assert "data-theme-icon-light" in body
    assert "data-theme-icon-dark" in body


def test_static_style_css_serves_severity_palette(layout_client: TestClient) -> None:
    """The static CSS file is reachable and ships the documented colours."""
    response = layout_client.get("/admin/static/style.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    body = response.text
    # P-FE-00 severity palette — exact hex values are part of the contract.
    assert "#16a34a" in body  # low — green-600
    assert "#ca8a04" in body  # medium — yellow-600
    assert "#dc2626" in body  # high — red-600
    assert "#a21caf" in body  # critical — fuchsia-700
    for cls in ("severity-low", "severity-medium", "severity-high", "severity-critical"):
        assert f".{cls}" in body, f"missing severity class .{cls}"


def test_shell_js_serves_expected_apis(layout_client: TestClient) -> None:
    """app.js exposes the documented hooks (theme toggle, token, htmx wiring)."""
    response = layout_client.get("/admin/static/js/app.js")
    assert response.status_code == 200
    body = response.text
    # Each behaviour required by P-FE-00 must be present.
    assert "toggleTheme" in body
    assert "Authorization" in body  # JWT injection
    assert "htmx:configRequest" in body
    assert "htmx:responseError" in body
    assert "HX-Redirect" in body
    assert "Escape" in body  # modal ESC dismissal
    assert "window.adminShell" in body  # public surface for the login page


def test_tailwind_config_sets_class_dark_mode(layout_client: TestClient) -> None:
    """tailwind-config.js wires ``class`` strategy + applies stored theme pre-paint."""
    body = layout_client.get("/admin/static/js/tailwind-config.js").text
    assert 'darkMode: "class"' in body
    assert "admin-theme" in body
    # Severity palette mirrored as Tailwind colour tokens for future utilities.
    assert "#16a34a" in body
    assert "#a21caf" in body


def test_layout_check_requires_auth() -> None:
    """Without the auth override, the layout-check page is JWT-gated."""
    from auth import get_current_user  # noqa: F401, PLC0415  (re-import for side effect)
    from web import (  # noqa: PLC0415
        mount_static,
        register_web_routes,
    )
    from web import router as web_router  # noqa: PLC0415

    register_web_routes()
    app = FastAPI()
    app.include_router(web_router, prefix="/admin")
    mount_static(app)
    with TestClient(app) as client:
        response = client.get("/admin/_layout-check")
    # Real auth dependency rejects anonymous callers with 401.
    assert response.status_code == 401
