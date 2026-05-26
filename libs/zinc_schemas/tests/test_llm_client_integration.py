"""Integration tests against a live LiteLLM proxy and Postgres."""

from __future__ import annotations

import os

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from zinc_schemas.llm_client import LLMClient

_MODEL_RUNS_DDL = """
CREATE SCHEMA IF NOT EXISTS theeyebeta;
CREATE TABLE IF NOT EXISTS theeyebeta.model_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid,
  provider text NOT NULL,
  model text NOT NULL,
  input_tokens int NOT NULL,
  output_tokens int NOT NULL,
  cache_read_tokens int DEFAULT 0,
  cache_write_tokens int DEFAULT 0,
  cost_usd numeric(10,6) NOT NULL,
  latency_ms int,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def _docker_available() -> bool:
    try:
        import docker  # noqa: PLC0415

        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


def _integration_enabled() -> bool:
    return os.environ.get("LITELLM_INTEGRATION", "").lower() in {"1", "true", "yes"}


@pytest.mark.integration
@pytest.mark.skipif(not _integration_enabled(), reason="set LITELLM_INTEGRATION=1 to run")
@pytest.mark.skipif(not _docker_available(), reason="Docker required for Postgres testcontainer")
async def test_live_litellm_writes_model_runs() -> None:
    """Call a real LiteLLM proxy and assert a model_runs row is inserted."""
    proxy_url = os.environ.get("LITELLM_PROXY_URL", "http://127.0.0.1:7020")
    virtual_key = os.environ.get("LITELLM_KEY_GUARD_SERVICE_CLASSIFIER") or os.environ.get(
        "LITELLM_VIRTUAL_KEY",
        "",
    )
    if not virtual_key.startswith("sk-"):
        pytest.skip("LITELLM_KEY_GUARD_SERVICE_CLASSIFIER or LITELLM_VIRTUAL_KEY required")

    model = os.environ.get("LITELLM_INTEGRATION_MODEL", "claude-haiku-4-5")

    with PostgresContainer("postgres:17-alpine") as postgres:
        dsn = postgres.get_connection_url()
        with psycopg.connect(dsn) as admin:
            admin.execute(_MODEL_RUNS_DDL)
            admin.commit()

        async with LLMClient(
            virtual_key,
            proxy_url,
            database_url=dsn,
        ) as client:
            result = await client.chat(
                model,
                [{"role": "user", "content": "Reply with exactly: pong"}],
                max_tokens=16,
                temperature=0.0,
            )

        assert result.model_used
        assert result.usage.prompt_tokens >= 0

        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                """
                SELECT provider, model, input_tokens, output_tokens, status, cost_usd
                  FROM theeyebeta.model_runs
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
            ).fetchone()

    assert row is not None
    provider, db_model, inp, out, status, cost = row
    assert status == "ok"
    assert db_model == result.model_used
    assert inp == result.usage.prompt_tokens
    assert out == result.usage.completion_tokens
    assert float(cost) == pytest.approx(result.cost_usd, rel=1e-3)
    assert provider in {"anthropic", "openai", "litellm"}
    assert result.content is not None
