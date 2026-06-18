"""End-to-end frontend tests (Playwright + axe-core) — P-FE-FINAL.

This module spins a real uvicorn process in a background thread and drives the
admin UI with Chromium via Playwright. Each of the eight server-rendered pages
(dashboard, orders, audit, agents, violations, costs, sql, proposals) is
checked for:

1. Login flow works (a real RS256 JWT is minted, then attached as
   ``Authorization: Bearer`` on every request).
2. Page renders without console / page errors.
3. One interactive htmx swap renders the expected fragment target.
4. axe-core finds **no critical-impact** WCAG violations.

The whole module is gated behind ``@pytest.mark.frontend`` so it only runs on
machines with Playwright + Chromium installed::

    uv sync --group dev
    playwright install chromium
    pytest services/admin_service/tests/test_frontend.py -m frontend
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

# Skip the whole module if Playwright is not installed in the current env.
# (Playwright lives in the workspace dev group; CI images / dev boxes that have
# not run ``uv sync --group dev`` + ``playwright install chromium`` will simply
# bypass this file.)
playwright_sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is required for the P-FE-FINAL e2e tests",
)

if TYPE_CHECKING:  # pragma: no cover — import for typing only.
    from playwright.sync_api import Browser, ConsoleMessage, Page

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from services.admin_service.tests.conftest import (
    _RecordingNats,  # noqa: E402 — sys.path tweak above.
)

# Pin axe-core to a version that ships ``axe.run`` returning a Promise.
_AXE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
_SERVER_BOOT_TIMEOUT_SECONDS = 30.0
_HTMX_SWAP_TIMEOUT_MS = 10_000

pytestmark = [pytest.mark.frontend]


class _InMemoryRedisStub:
    """Tiny async Redis lookalike — supports the four methods auth.py uses.

    The real refresh-token rotation only relies on ``set / get / delete / ping
    / aclose``; we don't model TTL expiry because test sessions are short.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def set(  # noqa: D401, A003
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool:
        del ex
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                removed += 1
        return removed

    async def aclose(self) -> None:
        self._store.clear()


async def _init_frontend_resources(settings: object) -> None:
    """asyncpg pool + recording NATS + in-memory Redis."""
    import asyncpg  # noqa: PLC0415
    import deps  # noqa: PLC0415

    deps._pool = await asyncpg.create_pool(  # noqa: SLF001
        dsn=settings.database_url,  # type: ignore[attr-defined]
        min_size=1,
        max_size=5,
        command_timeout=60,
    )
    deps._nats = _RecordingNats()  # noqa: SLF001
    deps._redis = _InMemoryRedisStub()  # noqa: SLF001
    deps._redis_ops = _InMemoryRedisStub()  # noqa: SLF001


async def _close_frontend_resources() -> None:
    import deps  # noqa: PLC0415

    if deps._pool is not None:
        await deps._pool.close()
        deps._pool = None
    if deps._redis is not None:
        await deps._redis.aclose()
        deps._redis = None
    if deps._redis_ops is not None:
        await deps._redis_ops.aclose()
        deps._redis_ops = None
    deps._nats = None


# --------------------------------------------------------------------------- #
# Session-scoped infrastructure: DB seed + uvicorn server + real JWT login.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def frontend_seeded_dsn(
    orders_integration_dsn: str,
    orders_page_integration_dsn: str,
    audit_integration_dsn: str,
    agents_integration_dsn: str,
    guard_integration_dsn: str,
    backtest_integration_dsn: str,
    costs_integration_dsn: str,
    sql_integration_dsn: str,
    proposals_integration_dsn: str,
    dashboard_integration_dsn: str,
) -> str:
    """Apply every domain seed once to the shared admin DSN.

    Each per-domain seed fixture is session-scoped and idempotent (``ON CONFLICT
    DO NOTHING`` everywhere), so chaining them on the same DSN gives us a
    single Postgres ready to render every UI page.
    """
    return dashboard_integration_dsn


def _find_free_port() -> int:
    """Return a port the OS deems currently free on ``127.0.0.1``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _rsa_keypair_pem() -> tuple[str, str]:
    """Generate an ephemeral RS256 PEM key-pair for the live test server."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _wait_for_server_ready(base_url: str) -> None:
    """Poll ``/admin/health`` until the uvicorn thread reports ready."""
    import httpx

    deadline = time.monotonic() + _SERVER_BOOT_TIMEOUT_SECONDS
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/admin/health", timeout=2.0)
            if resp.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001 — boot-loop probe.
            last_exc = exc
        time.sleep(0.2)
    raise RuntimeError(
        f"admin-service did not respond on {base_url} within "
        f"{_SERVER_BOOT_TIMEOUT_SECONDS:.0f}s (last error: {last_exc!r})",
    )


@pytest.fixture(scope="session")
def frontend_app_server(frontend_seeded_dsn: str) -> Iterator[dict[str, str]]:
    """Start uvicorn against the seeded DSN; yield ``{base_url, password}``.

    JWT keys and the bcrypt password are minted in-memory so the **real** login
    flow can be exercised (no FastAPI dependency override is installed).
    """
    import bcrypt
    import uvicorn

    from services.admin_service.tests.conftest import _admin_create_app

    create_app = _admin_create_app()
    from settings import Settings, get_settings

    private_pem, public_pem = _rsa_keypair_pem()
    plaintext_password = "frontend-test-password"
    password_hash = bcrypt.hashpw(plaintext_password.encode(), bcrypt.gensalt()).decode()

    get_settings.cache_clear()
    settings = Settings(
        database_url=frontend_seeded_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        admin_username="admin",
        admin_password_bcrypt=password_hash,
        jwt_private_key=private_pem,
        jwt_public_key=public_pem,
        audit_service_url="http://127.0.0.1:7110",
        cookie_secure=False,
    )

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    with ExitStack() as stack:
        stack.enter_context(patch("deps.init_resources", _init_frontend_resources))
        stack.enter_context(patch("deps.close_resources", _close_frontend_resources))

        app = create_app(settings=settings)

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
            access_log=False,
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(
            target=server.run,
            name="uvicorn-frontend-tests",
            daemon=True,
        )
        thread.start()
        try:
            _wait_for_server_ready(base_url)
            yield {"base_url": base_url, "password": plaintext_password}
        finally:
            server.should_exit = True
            thread.join(timeout=10.0)


@pytest.fixture(scope="session")
def jwt_token(frontend_app_server: dict[str, str]) -> str:
    """Log in via the real ``POST /admin/auth/login`` endpoint."""
    import httpx

    resp = httpx.post(
        f"{frontend_app_server['base_url']}/admin/auth/login",
        json={"username": "admin", "password": frontend_app_server["password"]},
        timeout=5.0,
    )
    assert resp.status_code == 200, f"login flow failed: {resp.status_code} {resp.text!r}"
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]
    return body["access_token"]


# --------------------------------------------------------------------------- #
# Per-test page fixture: authed Chromium context + console-error collector.
# --------------------------------------------------------------------------- #


def _attach_error_listeners(page: Page, sink: list[str]) -> None:
    """Pipe ``console.error`` + uncaught page errors into ``sink``."""

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            sink.append(f"console.error: {msg.text}")

    page.on("console", _on_console)
    page.on("pageerror", lambda exc: sink.append(f"pageerror: {exc}"))


@pytest.fixture
def authed_page(
    browser: Browser,
    jwt_token: str,
    frontend_app_server: dict[str, str],
) -> Iterator[tuple[Page, list[str]]]:
    """Yield a fresh Chromium page with the JWT pre-attached + error sink."""
    context = browser.new_context(
        extra_http_headers={"Authorization": f"Bearer {jwt_token}"},
        viewport={"width": 1280, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()
    errors: list[str] = []
    _attach_error_listeners(page, errors)
    try:
        yield page, errors
    finally:
        context.close()


# --------------------------------------------------------------------------- #
# axe-core helpers.
# --------------------------------------------------------------------------- #


def _inject_axe(page: Page) -> None:
    """Inject axe-core from the CDN, retry once on transient network error."""
    try:
        page.add_script_tag(url=_AXE_CDN_URL)
    except playwright_sync_api.Error:
        time.sleep(1.0)
        page.add_script_tag(url=_AXE_CDN_URL)


def _critical_a11y_violations(page: Page) -> list[dict[str, object]]:
    """Run axe-core on the current document; return critical-impact rows only.

    axe-core's JS API returns a result object whose ``violations`` field is a
    list of rule failures. Each row carries an ``impact`` of ``minor``,
    ``moderate``, ``serious`` or ``critical`` — we only fail the build on
    ``critical`` per the P-FE-FINAL acceptance bar.
    """
    _inject_axe(page)
    result: dict[str, object] = page.evaluate(
        """
        async () => {
            const out = await window.axe.run(document, {
                resultTypes: ['violations'],
                runOnly: {
                    type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
                }
            });
            return {
                violations: out.violations.map(v => ({
                    id: v.id,
                    impact: v.impact,
                    help: v.help,
                    helpUrl: v.helpUrl,
                    nodes: v.nodes.length
                }))
            };
        }
        """,
    )
    violations = result.get("violations") or []
    assert isinstance(violations, list)
    return [v for v in violations if isinstance(v, dict) and v.get("impact") == "critical"]


def _assert_clean_render(
    page: Page,
    errors: list[str],
    *,
    page_label: str,
) -> None:
    """Common assertion bundle: no console errors + 0 critical axe violations."""
    assert not errors, f"{page_label}: unexpected console / page errors: {errors}"
    critical = _critical_a11y_violations(page)
    assert critical == [], (
        f"{page_label}: axe-core reported {len(critical)} critical violation(s): {critical}"
    )


def _navigate(page: Page, base_url: str, path: str) -> None:
    """Goto + wait for htmx to attach to the document."""
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    page.wait_for_function("window.htmx !== undefined", timeout=_HTMX_SWAP_TIMEOUT_MS)


# --------------------------------------------------------------------------- #
# Login / auth gate.
# --------------------------------------------------------------------------- #


def test_login_flow_works(jwt_token: str) -> None:
    """``POST /admin/auth/login`` returns a valid RS256 access token.

    The ``jwt_token`` fixture itself performs the login and asserts ``200``;
    re-asserting here keeps the user-facing contract explicit (and lets the
    Playwright suite fail fast if auth ever regresses).
    """
    assert jwt_token.count(".") == 2, "JWT must be in header.payload.signature form"


def test_unauthenticated_request_is_rejected(
    frontend_app_server: dict[str, str],
) -> None:
    """Confirm the auth gate stays armed when no Bearer header is sent."""
    import httpx

    resp = httpx.get(
        f"{frontend_app_server['base_url']}/admin/orders/pending",
        timeout=5.0,
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Per-page e2e tests.
# --------------------------------------------------------------------------- #


def test_dashboard_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/`` renders stat cards + the refresh htmx swap re-renders them."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/")

    page.wait_for_selector('[data-test-id="stat-cards"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    page.locator('button[aria-label="Refresh stats"]').click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector('[data-test-id="stat-cards"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    _assert_clean_render(page, errors, page_label="dashboard")


def test_orders_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/orders`` renders + expanding a rationale snippet swaps inline."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/orders")

    page.wait_for_selector('[data-test-id="orders-tbody"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    expand_buttons = page.locator('[data-test-id="rationale-snippet"] button')
    if expand_buttons.count() > 0:
        expand_buttons.first.click()
        page.wait_for_selector(
            '[data-test-id="rationale-expanded"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="orders")


def test_audit_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/audit`` renders + the filter form swaps the table fragment."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/audit")

    page.wait_for_selector('[data-test-id="audit-table"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    limit_input = page.locator("#audit-filter-form input[name='limit']")
    if limit_input.count() > 0:
        limit_input.first.fill("25")
        page.locator("#audit-filter-form").evaluate("form => form.requestSubmit()")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(
            '[data-test-id="audit-table"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="audit")


def test_agents_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/agents`` renders + clicking an agent loads the runs panel."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/agents")

    page.wait_for_selector('[data-test-id="agent-list"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    agent_links = page.locator(
        '[data-test-id="agent-list"] [data-agent-id]',
    )
    if agent_links.count() > 0:
        agent_links.first.locator("button, a").first.click()
        page.wait_for_selector(
            '[data-test-id="agent-detail"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="agents")


def test_violations_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/violations`` renders + a filter change re-fetches the table."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/violations")

    page.wait_for_selector('[data-test-id="violations-table"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    severity = page.locator("#violations-filter-form select[name='severity']")
    if severity.count() > 0:
        severity.first.select_option("high")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(
            '[data-test-id="violations-table"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="violations")


def test_costs_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/costs`` renders 2 charts + the daily-window swap rebuilds one."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/costs")

    page.wait_for_selector('[data-test-id="costs-daily-card"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    page.wait_for_selector('[data-test-id="costs-agent-card"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    days_select = page.locator('select[name="days"]')
    if days_select.count() > 0:
        days_select.first.select_option("7")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(
            '[data-test-id="costs-daily-card"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="costs")


def test_sql_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/sql`` renders + running a SELECT swaps the result fragment."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/sql")

    page.wait_for_selector('[data-test-id="sql-run"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    page.locator('[data-test-id="sql-mode-read"]').check()
    # CodeMirror replaces the textarea but exposes the editor on the wrapper
    # div's ``.CodeMirror`` property. Drive it via ``setValue`` + ``save`` so
    # the form serialises the SELECT statement on submit.
    page.evaluate(
        """
        () => {
            const wrapper = document.querySelector('.CodeMirror');
            const cm = wrapper && wrapper.CodeMirror;
            if (cm) {
                cm.setValue('SELECT 1 AS one');
                cm.save();
            } else {
                const ta = document.getElementById('sql-statement');
                if (ta) ta.value = 'SELECT 1 AS one';
            }
        }
        """,
    )
    page.locator('[data-test-id="sql-run"]').click()
    page.wait_for_selector(
        '[data-test-id="sql-query-result"]',
        timeout=_HTMX_SWAP_TIMEOUT_MS,
    )
    _assert_clean_render(page, errors, page_label="sql")


def test_proposals_page(
    authed_page: tuple[Page, list[str]],
    frontend_app_server: dict[str, str],
) -> None:
    """``/admin/proposals`` renders + switching tabs swaps the panel content."""
    page, errors = authed_page
    _navigate(page, frontend_app_server["base_url"], "/admin/proposals")

    page.wait_for_selector('[data-test-id="proposals-list"]', timeout=_HTMX_SWAP_TIMEOUT_MS)
    approved_tab = page.locator('[data-test-id="proposals-tab-approved"]')
    if approved_tab.count() > 0:
        approved_tab.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(
            '[data-test-id="proposals-list"]',
            timeout=_HTMX_SWAP_TIMEOUT_MS,
        )
    _assert_clean_render(page, errors, page_label="proposals")
