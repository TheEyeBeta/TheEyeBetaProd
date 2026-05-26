"""pytest fixtures for agent-runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# zinc_test registers itself via the pytest11 entry-point — no explicit
# pytest_plugins declaration needed (double-registration breaks pluggy).

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_AR_SQL = Path(__file__).resolve().parent / "sql"


@pytest.fixture(scope="session")
def _agent_runtime_seed(alembic_upgraded: str) -> None:
    """Seed macro-lead agent SQL on top of the shared alembic fixture."""
    from zinc_test._infra import _normalize_psycopg_dsn, _run_sql_file  # noqa: PLC0415

    _run_sql_file(_normalize_psycopg_dsn(alembic_upgraded), _AR_SQL / "seed_macro_lead_agent.sql")


@pytest.fixture
def integration_env(
    integration_infra: object,
    _agent_runtime_seed: None,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Apply env vars for one agent-runtime integration test."""
    from zinc_test import IntegrationInfra  # noqa: PLC0415

    infra: IntegrationInfra = integration_infra  # type: ignore[assignment]

    os.environ.setdefault("LITELLM_DB_PASSWORD", "integration_test_litellm")

    monkeypatch.setenv("DATABASE_URL", infra.database_url)
    monkeypatch.setenv("NATS_URL", infra.nats_url)
    monkeypatch.setenv("MINIO_ENDPOINT", infra.minio_endpoint)
    monkeypatch.setenv("MINIO_ROOT_USER", infra.minio_access_key)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", infra.minio_secret_key)
    monkeypatch.setenv("MINIO_SNAPSHOT_BUCKET", infra.minio_bucket)
    monkeypatch.setenv("REDIS_URL", infra.redis_url)
    monkeypatch.setenv("LITELLM_KEY_AGENT_RUNTIME_EXECUTORS", "sk-integration-test-agent-runtime")
    monkeypatch.setenv("LITELLM_PROXY_URL", "http://llm-gateway.test:4000")
    monkeypatch.setenv("GUARD_SERVICE_HTTP_URL", "")
    return infra
