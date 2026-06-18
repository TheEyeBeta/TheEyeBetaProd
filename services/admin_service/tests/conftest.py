"""Shared fixtures for admin-service integration tests."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import patch

import asyncpg
import httpx
import pytest
from httpx import AsyncClient

# ``zinc_test`` registers itself via the ``pytest11`` entry-point in
# ``libs/zinc_test/pyproject.toml`` (auto-loaded once ``uv sync`` installs the
# package). No explicit ``pytest_plugins`` declaration is needed here — adding
# one would cause pluggy to register the same module under two different names
# and raise ``Plugin already registered under a different name``.

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_SQL_DIR = Path(__file__).resolve().parent / "sql"

if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from zinc_test._infra import (  # noqa: E402
    _normalize_psycopg_dsn,
    _run_sql_file,
    app_dsn_from_admin,
)

# Re-export so the ``importlib.util``-based loaders in test files (e.g.
# ``test_sql.py``, ``test_proposals.py``) can pick the helper up off the
# admin conftest module without depending on ``zinc_test`` internals directly.
__all__ = ["_normalize_psycopg_dsn", "_run_sql_file", "app_dsn_from_admin"]

_BaseASGITransport = httpx.ASGITransport


class ASGITransport(_BaseASGITransport):
    """httpx 0.28-compatible transport with the old ``lifespan='on'`` hook."""

    def __init__(
        self,
        *args: Any,
        lifespan: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._lifespan_mode = lifespan
        self._lifespan_context: Any | None = None
        self._lifespan_started = False
        self._lifespan_app = args[0] if args else kwargs.get("app")
        super().__init__(*args, **kwargs)

    async def _ensure_lifespan_started(self) -> None:
        if self._lifespan_mode != "on" or self._lifespan_started:
            return
        if self._lifespan_app is None:
            return
        self._lifespan_context = self._lifespan_app.router.lifespan_context(
            self._lifespan_app,
        )
        await self._lifespan_context.__aenter__()
        self._lifespan_started = True

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await self._ensure_lifespan_started()
        return await super().handle_async_request(request)

    async def aclose(self) -> None:
        try:
            await super().aclose()
        finally:
            if self._lifespan_started and self._lifespan_context is not None:
                await self._lifespan_context.__aexit__(None, None, None)
                self._lifespan_started = False


httpx.ASGITransport = ASGITransport

_ADMIN_TOP_LEVEL_MODULES = {
    "audit_log",
    "auth",
    "auth_mfa",
    "auth_sessions",
    "deps",
    "errors",
    "main",
    "rbac",
    "settings",
    "web",
}


def _purge_admin_modules() -> None:
    """Drop top-level admin-service modules so dependency overrides bind correctly."""
    for name, module in list(sys.modules.items()):
        is_admin_namespace = (
            name in _ADMIN_TOP_LEVEL_MODULES
            or name == "api"
            or name.startswith("api.")
            or name == "lib"
            or name.startswith("lib.")
        )
        if not is_admin_namespace:
            continue
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            sys.modules.pop(name, None)
            continue
        try:
            path = Path(module_file).resolve()
        except OSError:
            sys.modules.pop(name, None)
            continue
        if path.is_relative_to(_SERVICE_ROOT) or name in _ADMIN_TOP_LEVEL_MODULES:
            sys.modules.pop(name, None)


def _admin_create_app() -> Any:
    """Return admin-service create_app even after other tests mutate sys.path."""
    service_root = str(_SERVICE_ROOT)
    if service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)
    _purge_admin_modules()
    return import_module("main").create_app


PENDING_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440001"
APPROVED_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440002"
PENDING_ORDER_ID_2 = "cc0e8400-e29b-41d4-a716-446655440003"


class _RecordingNats:
    """In-memory NATS stub that records published messages."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))

    async def drain(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _MockRedis:
    """In-memory Redis stub for integration tests."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,  # noqa: ARG002
        nx: bool = False,
    ) -> bool | None:
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def getdel(self, key: str) -> str | None:
        return self._data.pop(key, None)

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
            if key in self._sets:
                del self._sets[key]
                count += 1
        return count

    async def sadd(self, key: str, member: str) -> int:
        self._sets.setdefault(key, set()).add(member)
        return 1

    async def srem(self, key: str, member: str) -> int:
        bucket = self._sets.get(key)
        if bucket and member in bucket:
            bucket.remove(member)
            return 1
        return 0

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


async def _init_test_resources(settings: object) -> None:
    """Start asyncpg pool, mock NATS, and in-memory Redis."""
    import deps  # noqa: PLC0415

    deps._pool = await asyncpg.create_pool(  # noqa: SLF001
        dsn=settings.database_url,  # type: ignore[attr-defined]
        min_size=1,
        max_size=5,
        command_timeout=60,
    )
    deps._nats = _RecordingNats()  # noqa: SLF001
    mock_redis = _MockRedis()
    deps._redis = mock_redis  # noqa: SLF001
    deps._redis_ops = mock_redis  # noqa: SLF001


async def _close_test_resources() -> None:
    import deps  # noqa: PLC0415

    if deps._pool is not None:
        await deps._pool.close()
        deps._pool = None
    deps._nats = None
    deps._redis = None
    deps._redis_ops = None


@pytest.fixture(scope="session")
def admin_integration_dsn(alembic_upgraded: str) -> str:
    """Postgres with migrations — returns tb_app DSN (delegates to shared alembic_upgraded)."""
    return app_dsn_from_admin(alembic_upgraded)


@pytest.fixture(scope="session")
def orders_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with order seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_orders.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def audit_integration_dsn(alembic_upgraded: str) -> str:
    """Postgres with audit log + checkpoint seed data."""
    _run_sql_file(alembic_upgraded, _SQL_DIR / "seed_audit.sql")
    return app_dsn_from_admin(alembic_upgraded)


@pytest.fixture(scope="session")
def agents_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with agent registry + agent_runs seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_agents.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def guard_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with guard_violations seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_guard.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def backtest_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with strategies + backtest_runs seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_backtest.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def costs_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with model_runs + api_costs seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_costs.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def sql_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with the admin_sql_sandbox table seeded."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_sql.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def proposals_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with proposals + strategies seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_proposals.sql")
    return admin_integration_dsn


@pytest.fixture(scope="session")
def dashboard_integration_dsn(alembic_upgraded: str) -> str:
    """Postgres seeded for the dashboard's four stat-card queries."""
    _run_sql_file(alembic_upgraded, _SQL_DIR / "seed_dashboard.sql")
    return app_dsn_from_admin(alembic_upgraded)


@pytest.fixture(scope="session")
def orders_page_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres seeded with pending orders that have rationale metadata."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_orders_page.sql")
    return admin_integration_dsn


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bypass JWT — dependency override supplies the user."""
    return {"Authorization": "Bearer test-token"}


async def _admin_client_for_dsn(
    dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """Yield httpx client + NATS stub for a bootstrapped DSN."""
    create_app = _admin_create_app()
    from auth import get_current_user  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(
        database_url=dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        admin_password_bcrypt="",
        jwt_private_key="",
        jwt_public_key="",
        audit_service_url="http://127.0.0.1:7110",
    )

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        await _init_test_resources(settings)
        import deps  # noqa: PLC0415

        deps.bind_app_state(app, settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "test-operator"}

        app.dependency_overrides[get_current_user] = _fake_user
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                nats_stub = deps._nats
                assert isinstance(nats_stub, _RecordingNats)
                yield client, nats_stub
        finally:
            app.dependency_overrides.clear()
            await _close_test_resources()


@pytest.fixture
async def admin_client(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with migrations only (no domain seed)."""
    async for client in _admin_client_for_dsn(admin_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def orders_admin_client(
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with order seed data."""
    async for client in _admin_client_for_dsn(orders_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def audit_admin_client(
    audit_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with audit log + checkpoint seed data."""
    async for client in _admin_client_for_dsn(audit_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def agents_admin_client(
    agents_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with agent registry + runs seed data."""
    async for client in _admin_client_for_dsn(agents_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def guard_admin_client(
    guard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with guard_violations seed data."""
    async for client in _admin_client_for_dsn(guard_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def backtest_admin_client(
    backtest_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with backtest_runs seed data."""
    async for client in _admin_client_for_dsn(backtest_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def costs_admin_client(
    costs_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with model_runs + api_costs seed data."""
    async for client in _admin_client_for_dsn(costs_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def sql_admin_client(
    sql_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with the admin_sql_sandbox table seeded."""
    async for client in _admin_client_for_dsn(sql_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def proposals_admin_client(
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client with proposals + strategies seed data."""
    async for client in _admin_client_for_dsn(proposals_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def dashboard_admin_client(
    dashboard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client wired to the dashboard seed DSN."""
    async for client in _admin_client_for_dsn(dashboard_integration_dsn, auth_headers):
        yield client


@pytest.fixture
async def orders_page_admin_client(
    orders_page_integration_dsn: str,
    auth_headers: dict[str, str],
) -> AsyncIterator[tuple[AsyncClient, _RecordingNats]]:
    """HTTP client wired to the orders-page seed DSN."""
    async for client in _admin_client_for_dsn(orders_page_integration_dsn, auth_headers):
        yield client
