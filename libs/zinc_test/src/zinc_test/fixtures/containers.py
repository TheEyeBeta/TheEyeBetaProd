"""Session-scoped testcontainers fixtures for Postgres, Redis, NATS, and MinIO."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from zinc_test._infra import docker_available

if TYPE_CHECKING:
    pass


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Timescale + pgvector Postgres 17 container (session-scoped).

    Yields the live PostgresContainer so callers can call
    ``container.get_connection_url()`` to obtain the admin DSN.
    """
    if not docker_available():
        pytest.skip("Docker daemon not available (required for testcontainers)")

    container = (
        PostgresContainer("timescale/timescaledb-ha:pg17")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "theeyebeta")
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """Redis 7 Alpine container (session-scoped).

    Yields the live RedisContainer; use ``container.get_connection_url()``
    for the redis:// URL.
    """
    if not docker_available():
        pytest.skip("Docker daemon not available (required for testcontainers)")

    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def nats_container() -> Generator[DockerContainer, None, None]:
    """NATS 2 Alpine container with JetStream enabled (session-scoped).

    Yields the live DockerContainer; build the URL with::

        host = container.get_container_host_ip()
        port = container.get_exposed_port(4222)
        url  = f"nats://{host}:{port}"
    """
    if not docker_available():
        pytest.skip("Docker daemon not available (required for testcontainers)")

    container = (
        DockerContainer("nats:2-alpine").with_command("-js -m 8222").with_exposed_ports(4222)
    )
    container.start()
    try:
        wait_for_logs(container, "Listening for client connections")
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def minio_container() -> Generator[DockerContainer, None, None]:
    """MinIO container (session-scoped).

    Default credentials: ``minioadmin`` / ``minioadmin123``.
    Build the endpoint with::

        host     = container.get_container_host_ip()
        port     = container.get_exposed_port(9000)
        endpoint = f"{host}:{port}"
    """
    if not docker_available():
        pytest.skip("Docker daemon not available (required for testcontainers)")

    container = (
        DockerContainer("minio/minio:latest")
        .with_command("server /data --console-address :9001")
        .with_env("MINIO_ROOT_USER", "minioadmin")
        .with_env("MINIO_ROOT_PASSWORD", "minioadmin123")
        .with_exposed_ports(9000)
    )
    container.start()
    try:
        wait_for_logs(container, "API:")
        yield container
    finally:
        container.stop()
