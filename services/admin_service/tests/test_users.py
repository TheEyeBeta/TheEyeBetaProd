"""Tests for Users/Permissions RBAC control plane."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

MASTER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OPERATOR_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture(scope="session")
def users_integration_dsn(admin_integration_dsn: str) -> str:
    from tests.conftest import _run_sql_file

    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_users.sql")
    return admin_integration_dsn


@pytest.fixture
async def users_master_client(users_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=users_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        admin_password_bcrypt="",
        jwt_private_key="",
        jwt_public_key="",
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
async def users_operator_client(users_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=users_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
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
def test_matrix_includes_users_control_plane() -> None:
    from control_matrix.registry import build_control_matrix

    ids = {e.id for e in build_control_matrix()}
    assert "admin.users.control-plane" in ids
    entry = next(e for e in build_control_matrix() if e.id == "master-admin.rbac")
    assert entry.audit_implemented
    assert entry.frontend_location == "/admin/users"


@pytest.mark.integration
@pytest.mark.unit
async def test_operator_forbidden_on_list(users_operator_client: AsyncClient) -> None:
    resp = await users_operator_client.get("/admin/users")
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.unit
async def test_master_admin_lists_users(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.get("/admin/users")
    assert resp.status_code == 200
    body = resp.json()
    assert "users" in body
    usernames = {u["username"] for u in body["users"]}
    assert "master-admin" in usernames
    assert "operator-one" in usernames
    for user in body["users"]:
        assert "password" not in user
        assert "password_hash" not in user


@pytest.mark.unit
def test_require_dangerous_confirm_rejects_missing_header() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm

    body = DangerousActionRequest(reason="test", confirm=True)
    with pytest.raises(HTTPException) as exc:
        require_dangerous_confirm(body, None)
    assert exc.value.status_code == 422


@pytest.mark.unit
def test_redact_payload_strips_secrets() -> None:
    from users.service import AdminUsersService

    out = AdminUsersService._redact_payload(
        {"reason": "ok", "password": "secret", "token": "abc"},
    )
    assert "password" not in out
    assert "token" not in out
    assert out["reason"] == "ok"


@pytest.mark.integration
@pytest.mark.unit
async def test_grant_role_requires_confirm(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.post(
        f"/admin/users/{OPERATOR_ID}/roles",
        json={"role": "MASTER_ADMIN", "reason": "test grant", "confirm": False},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.unit
async def test_grant_and_revoke_role(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.post(
        f"/admin/users/{OPERATOR_ID}/roles",
        json={"role": "MASTER_ADMIN", "reason": "temporary elevation", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert "MASTER_ADMIN" in resp.json()["roles"]

    resp = await users_master_client.request(
        "DELETE",
        f"/admin/users/{OPERATOR_ID}/roles/MASTER_ADMIN",
        json={
            "role": "MASTER_ADMIN",
            "reason": "revoke elevation",
            "confirm": True,
            "allow_final_master_removal": False,
        },
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert "MASTER_ADMIN" not in resp.json()["roles"]


@pytest.mark.integration
@pytest.mark.unit
async def test_cannot_remove_final_master_admin(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.request(
        "DELETE",
        f"/admin/users/{MASTER_ID}/roles/MASTER_ADMIN",
        json={
            "role": "MASTER_ADMIN",
            "reason": "attempt remove last",
            "confirm": True,
            "allow_final_master_removal": False,
        },
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 409


@pytest.mark.integration
@pytest.mark.unit
async def test_disable_user_writes_audit(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.post(
        f"/admin/users/{OPERATOR_ID}/disable",
        json={"reason": "offboarding test", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    detail = await users_master_client.get(f"/admin/users/{OPERATOR_ID}")
    actions = [row["action"] for row in detail.json()["audit_history"]]
    assert "disable.admin_user" in actions

    await users_master_client.post(
        f"/admin/users/{OPERATOR_ID}/enable",
        json={"reason": "restore test user", "confirm": True},
        headers={"X-Confirm": "true"},
    )


@pytest.mark.integration
@pytest.mark.unit
async def test_users_page_renders_html(users_master_client: AsyncClient) -> None:
    resp = await users_master_client.get(
        "/admin/users",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "Users / Permissions" in resp.text
    assert "master-admin" in resp.text
