"""DB fixtures: alembic_upgraded bootstraps the schema; seed_data loads app seeds."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from zinc_test._infra import (
    IntegrationInfra,
    app_dsn_from_admin,
    bootstrap_database,
    dsn_with_database,
    seed_agents,
)
from zinc_test.fixtures.containers import (
    minio_container,  # noqa: F401 – re-exported for dependent fixture resolution
    nats_container,  # noqa: F401
    redis_container,  # noqa: F401
)


def _redis_url(container: RedisContainer) -> str:
    """Return a redis:// URL across testcontainers versions."""
    get_url = getattr(container, "get_connection_url", None)
    if get_url is not None:
        return str(get_url())
    host = container.get_container_host_ip()
    port = container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def alembic_upgraded(postgres_container: PostgresContainer) -> Generator[str, None, None]:
    """Bootstrap the test DB and run ``alembic upgrade head``.

    Yields the *admin* DSN (``postgresql://postgres:postgres@host:port/theeyebeta``).
    Downstream fixtures should call ``app_dsn_from_admin(dsn)`` to get the
    application-role URL.
    """
    admin_dsn = dsn_with_database(postgres_container.get_connection_url(), "theeyebeta")
    bootstrap_database(admin_dsn)
    yield admin_dsn


@pytest.fixture(scope="session")
def seed_data(alembic_upgraded: str) -> Generator[str, None, None]:
    """Run ``db/seeds/agents.py`` after migrations are applied.

    Yields the same admin DSN as ``alembic_upgraded``.
    """
    seed_agents(alembic_upgraded)
    yield alembic_upgraded


@pytest.fixture(scope="session")
def integration_infra(
    seed_data: str,
    redis_container: object,  # noqa: F811 – pytest fixture request; import above is re-export
    nats_container: object,  # noqa: F811
    minio_container: object,  # noqa: F811
) -> IntegrationInfra:
    """Composite fixture: all four containers + migrations + seeds.

    Yields an :class:`~zinc_test.IntegrationInfra` dataclass with every
    endpoint your service needs to build its Settings for integration tests.
    """
    from testcontainers.core.container import DockerContainer  # noqa: PLC0415
    from testcontainers.redis import RedisContainer  # noqa: PLC0415

    admin_dsn = seed_data

    assert isinstance(redis_container, RedisContainer)
    assert isinstance(nats_container, DockerContainer)
    assert isinstance(minio_container, DockerContainer)

    nats_host = nats_container.get_container_host_ip()
    nats_port = nats_container.get_exposed_port(4222)
    minio_host = minio_container.get_container_host_ip()
    minio_port = minio_container.get_exposed_port(9000)

    return IntegrationInfra(
        postgres_admin_url=admin_dsn,
        database_url=app_dsn_from_admin(admin_dsn),
        redis_url=_redis_url(redis_container),
        nats_url=f"nats://{nats_host}:{nats_port}",
        minio_endpoint=f"{minio_host}:{minio_port}",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin123",  # noqa: S106
        minio_bucket="theeyebeta-snapshots",
    )
