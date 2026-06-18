"""Integration tests for ``/admin/agents`` (page + fragments).

Uses the existing ``seed_agents.sql`` fixture (2 agents: ``technical-analyst``
with 5 runs, ``macro-lead`` with 0 runs).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

AGENT_ID = "technical-analyst"
SNAPSHOT_ID = UUID("11111111-2222-3333-4444-555555555555")
RUNTIME_RUN_ID = UUID("99999999-aaaa-bbbb-cccc-dddddddddddd")


# ---------------------------------------------------------------- HTML page


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agents_page_renders_two_pane_html(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/agents`` with ``Accept: text/html`` renders the two-pane shell."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents",
        headers={**auth_headers, "Accept": "text/html"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # Top-level shell
    assert "<html" in body
    assert 'data-page="agents"' in body
    assert 'aria-current="page"' in body
    # Left pane: both agents listed
    assert 'data-test-id="agent-list"' in body
    assert "technical-analyst" in body
    assert "macro-lead" in body
    # Right pane placeholder
    assert "Select an agent" in body
    # Run Now buttons
    assert "/admin/agents/fragments/technical-analyst/run-modal" in body
    # CDN includes
    assert "markdown-it" in body
    assert "highlight.js" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agents_page_returns_json_when_accept_is_json(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/agents`` with default Accept (``*/*``) keeps the JSON contract."""
    client, _ = agents_admin_client
    # The original JSON test in tests/test_agents.py sends no Accept header.
    response = await client.get("/admin/agents", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    ids = {row["id"] for row in body["agents"]}
    assert AGENT_ID in ids


# ---------------------------------------------------------------- Fragment: runs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_runs_fragment_returns_partial(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The Recent runs fragment is a standalone partial swapped via outerHTML."""
    client, _ = agents_admin_client
    response = await client.get(
        f"/admin/agents/fragments/{AGENT_ID}/runs",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    # Partial (no full doc)
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
    # Shell + active tab
    assert 'data-test-id="agent-detail"' in body
    assert f'data-agent-id="{AGENT_ID}"' in body
    assert 'data-tab="runs"' in body
    assert 'data-test-id="agent-runs-panel"' in body
    # 5 seeded runs, mix of succeeded + failed
    assert body.count("data-run-id=") == 5
    assert "succeeded" in body
    assert "failed" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_runs_fragment_404_for_unknown_agent(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Unknown agent → 404."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents/fragments/does-not-exist/runs",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- Fragment: constitution


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_constitution_fragment_renders_markdown_source(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The Constitution fragment emits the raw markdown inside a ``<script>`` tag."""
    client, _ = agents_admin_client
    response = await client.get(
        f"/admin/agents/fragments/{AGENT_ID}/constitution",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="agent-constitution-panel"' in body
    assert 'data-tab="constitution"' in body
    assert "data-constitution-source" in body
    assert "data-constitution-target" in body
    # Real file content — agents/technical-analyst.md has a "# Role" heading.
    assert "# Role" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_constitution_fragment_404_for_unknown_agent(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Unknown agent → 404 (not a flash card)."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents/fragments/does-not-exist/constitution",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- Fragment: run modal


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_modal_fragment(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The Run Now modal renders with form action targeting the run fragment."""
    client, _ = agents_admin_client
    response = await client.get(
        f"/admin/agents/fragments/{AGENT_ID}/run-modal",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="agent-run-modal"' in body
    assert f'hx-post="/admin/agents/fragments/{AGENT_ID}/run"' in body
    assert 'name="snapshot_id"' in body
    assert 'name="kind"' in body
    assert 'name="prompt"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_modal_unknown_agent_404(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Modal route returns 404 for an unknown agent (defence in depth)."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents/fragments/does-not-exist/run-modal",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- Fragment: run


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_fragment_happy_path(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Posting the form proxies to agent-runtime, audits, and returns a success flash."""
    client, _ = agents_admin_client

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"run_id": str(RUNTIME_RUN_ID), "status": "started"}

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any]) -> _Resp:
            assert json["snapshot_id"] == str(SNAPSHOT_ID)
            assert json["kind"] == "manual"
            return _Resp()

    with patch("api.agents.httpx.AsyncClient", _StubClient):
        response = await client.post(
            f"/admin/agents/fragments/{AGENT_ID}/run",
            headers=auth_headers,
            data={
                "snapshot_id": str(SNAPSHOT_ID),
                "kind": "manual",
                "prompt": "  please re-analyse  ",
            },
        )
    assert response.status_code == 200
    body = response.text
    assert "Run started" in body
    assert str(RUNTIME_RUN_ID) in body
    # HX-Trigger flash event for the global toast region.
    assert "HX-Trigger" in response.headers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_fragment_runtime_unreachable_returns_flash(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Runtime errors are surfaced as a flash card with the upstream status."""
    client, _ = agents_admin_client

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any]) -> Any:  # noqa: ARG002
            import httpx  # noqa: PLC0415

            raise httpx.ConnectError("connection refused")

    with patch("api.agents.httpx.AsyncClient", _StubClient):
        response = await client.post(
            f"/admin/agents/fragments/{AGENT_ID}/run",
            headers=auth_headers,
            data={
                "snapshot_id": str(SNAPSHOT_ID),
                "kind": "manual",
            },
        )
    assert response.status_code == 200
    body = response.text
    assert "Run failed" in body
    assert "503" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_fragment_unknown_agent(
    agents_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Submitting to a non-existent agent returns a flash 404, not a 500."""
    client, _ = agents_admin_client
    response = await client.post(
        "/admin/agents/fragments/does-not-exist/run",
        headers=auth_headers,
        data={
            "snapshot_id": str(SNAPSHOT_ID),
            "kind": "manual",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "Run failed" in body
    assert "404" in body


# ---------------------------------------------------------------- Auth gate


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agents_page_requires_auth(
    agents_integration_dsn: str,
) -> None:
    """All agents-page routes are JWT-gated."""
    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(database_url=agents_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            assert (
                await anon.get("/admin/agents", headers={"Accept": "text/html"})
            ).status_code == 401
            assert (await anon.get(f"/admin/agents/fragments/{AGENT_ID}/runs")).status_code == 401
            assert (
                await anon.get(f"/admin/agents/fragments/{AGENT_ID}/constitution")
            ).status_code == 401
            assert (
                await anon.get(f"/admin/agents/fragments/{AGENT_ID}/run-modal")
            ).status_code == 401
            assert (
                await anon.post(
                    f"/admin/agents/fragments/{AGENT_ID}/run",
                    data={"snapshot_id": str(SNAPSHOT_ID), "kind": "manual"},
                )
            ).status_code == 401
