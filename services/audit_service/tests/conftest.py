"""pytest fixtures for audit-service."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

# zinc_test registers itself via the pytest11 entry-point — no explicit
# pytest_plugins declaration needed (double-registration breaks pluggy).


@dataclass(frozen=True)
class PostgresInfra:
    """tb_app DSN for audit integration tests."""

    database_url: str


@pytest.fixture(scope="session")
def postgres_infra(alembic_upgraded: str) -> PostgresInfra:
    """Postgres with full Alembic migrations (delegates to shared fixture)."""
    from zinc_test._infra import app_dsn_from_admin  # noqa: PLC0415

    return PostgresInfra(database_url=app_dsn_from_admin(alembic_upgraded))
