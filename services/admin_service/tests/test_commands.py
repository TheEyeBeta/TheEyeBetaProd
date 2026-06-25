"""Tests for allowlisted command console (Prompt 15)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


@pytest.fixture
async def command_master_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        edge_mode="local",
    )
    with (
        patch("main.init_resources", _init_test_resources),
        patch("main.close_resources", _close_test_resources),
    ):
        app = create_app(settings)

        async def _master() -> dict[str, Any]:
            return {"sub": "master-admin", "roles": ["MASTER_ADMIN", "operator"]}

        app.dependency_overrides[get_current_user] = _master
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.fixture
async def command_operator_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        edge_mode="local",
    )
    with (
        patch("main.init_resources", _init_test_resources),
        patch("main.close_resources", _close_test_resources),
    ):
        app = create_app(settings)

        async def _operator() -> dict[str, Any]:
            return {"sub": "operator-one", "roles": ["operator"]}

        app.dependency_overrides[get_current_user] = _operator
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.mark.unit
def test_matrix_includes_command_console_entries() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.commands.registry" in ids
    assert "admin.commands.run" in ids
    assert "command.edge.routes.check" in ids


@pytest.mark.unit
def test_registry_maps_to_executor_handlers() -> None:
    from command_control.executor import CommandExecutor
    from command_control.registry import COMMANDS

    executor = CommandExecutor()
    dispatch = {
        "worker.run": executor._worker_run,
        "worker.stop": executor._worker_stop,
        "timer.disable": executor._timer_disable,
        "service.restart": executor._service_restart,
        "edge.routes.check": executor._edge_routes_check,
        "cloudflare.status": executor._cloudflare_status,
        "dataapi.health": executor._dataapi_health,
        "trading.halt": executor._trading_halt,
        "audit.verify": executor._audit_verify,
        "risk.compute": executor._risk_compute,
        "broker.test": executor._broker_test,
        "backtest.run": executor._backtest_run,
        "agent.run": executor._agent_run,
    }
    for cmd in COMMANDS:
        assert cmd.id in dispatch, f"missing executor for {cmd.id}"
        assert cmd.backend_route, f"missing backend route for {cmd.id}"


@pytest.mark.unit
def test_edge_routes_command_exists_in_registry() -> None:
    from command_control.parser import parse_command
    from command_control.registry import COMMANDS_BY_ID

    assert "edge.routes.check" in COMMANDS_BY_ID
    parsed = parse_command("EDGE ROUTES CHECK")
    assert parsed.definition.id == "edge.routes.check"
    assert parsed.definition.backend_route == "POST /admin/edge/routes/check"


@pytest.mark.unit
def test_unknown_command_rejected_by_parser() -> None:
    from command_control.parser import parse_command

    with pytest.raises(ValueError, match="Unknown command"):
        parse_command("SHELL RUN rm -rf /")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_command_rejected_by_api(command_master_client: AsyncClient) -> None:
    resp = await command_master_client.post(
        "/admin/commands/run",
        json={"command": "EXEC bash -c id", "reason": "nope", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 422
    assert "Unknown command" in resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dangerous_command_requires_confirm_and_reason(
    command_master_client: AsyncClient,
) -> None:
    blocked = await command_master_client.post(
        "/admin/commands/run",
        json={"command": "TRADING HALT", "reason": "", "confirm": False},
    )
    assert blocked.status_code == 422

    missing_header = await command_master_client.post(
        "/admin/commands/run",
        json={"command": "TRADING HALT", "reason": "incident", "confirm": True},
    )
    assert missing_header.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_commands_returns_allowlist(command_master_client: AsyncClient) -> None:
    resp = await command_master_client.get("/admin/commands")
    assert resp.status_code == 200
    body = resp.json()
    ids = {row["id"] for row in body["commands"]}
    assert "edge.routes.check" in ids
    assert "worker.run" in ids
    assert len(body["commands"]) >= 13


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preview_unknown_command(command_master_client: AsyncClient) -> None:
    resp = await command_master_client.post(
        "/admin/commands/preview",
        json={"command": "DROP DATABASE production"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is False
    assert "Unknown command" in (body.get("denial_reason") or "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edge_routes_check_command_audited(command_operator_client: AsyncClient) -> None:
    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"ok": True, "routes": {}, "drift_report": {}}
    with patch(
        "edge.service.EdgeRegistryService.run_routes_check",
        new=AsyncMock(return_value=mock_result),
    ):
        resp = await command_operator_client.post(
            "/admin/commands/run",
            json={"command": "EDGE ROUTES CHECK", "reason": None, "confirm": False},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["command_id"] == "edge.routes.check"
    assert body["status"] == "succeeded"
    assert body["audited"] is True
    assert body["backend_route"] == "POST /admin/edge/routes/check"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_command_run_persisted(command_operator_client: AsyncClient) -> None:
    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"ok": True, "routes": {}, "drift_report": {}}
    with patch(
        "edge.service.EdgeRegistryService.run_routes_check",
        new=AsyncMock(return_value=mock_result),
    ):
        run = await command_operator_client.post(
            "/admin/commands/run",
            json={"command": "EDGE ROUTES CHECK"},
        )
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    detail = await command_operator_client.get(f"/admin/commands/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["command_text"] == "EDGE ROUTES CHECK"
    assert detail.json()["audit_link"] == "/admin/audit"

    history = await command_operator_client.get("/admin/commands/runs")
    assert history.status_code == 200
    assert any(row["id"] == run_id for row in history.json()["runs"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_console_page_renders(command_master_client: AsyncClient) -> None:
    resp = await command_master_client.get("/admin/console", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    body = resp.text
    assert "Command Console" in body
    assert "EDGE ROUTES CHECK" in body
    assert "/admin/audit" in body
