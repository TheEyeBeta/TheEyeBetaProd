"""Shared fixtures for admin-service integration tests."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

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


async def _init_test_resources(settings: object) -> None:
    """Start only asyncpg pool and mock NATS."""
    import deps  # noqa: PLC0415

    deps._pool = await asyncpg.create_pool(  # noqa: SLF001
        dsn=settings.database_url,  # type: ignore[attr-defined]
        min_size=1,
        max_size=5,
        command_timeout=60,
    )
    deps._nats = _RecordingNats()  # noqa: SLF001
    deps._redis = None  # noqa: SLF001
    deps._redis_ops = None  # noqa: SLF001


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
def audit_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with audit log + checkpoint seed data."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_audit.sql")
    return admin_integration_dsn


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
def dashboard_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres seeded for the dashboard's four stat-card queries."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_dashboard.sql")
    return admin_integration_dsn


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
    from auth import get_current_user  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
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
        app = create_app(settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "test-operator"}

        app.dependency_overrides[get_current_user] = _fake_user
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            import deps  # noqa: PLC0415

            nats_stub = deps._nats
            assert isinstance(nats_stub, _RecordingNats)
            yield client, nats_stub
        app.dependency_overrides.clear()


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
