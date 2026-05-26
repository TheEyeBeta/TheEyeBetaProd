"""Shared fixtures for data-ingestion unit and integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# zinc_test registers itself via the pytest11 entry-point — no explicit
# pytest_plugins declaration needed (double-registration breaks pluggy).

# VCR helpers (kept here because they reference local cassette files)
CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture
def cassette_dir() -> Path:
    """Directory containing VCR YAML cassettes."""
    return CASSETTE_DIR


@pytest.fixture
def vcr_config() -> dict[str, object]:
    """VCR.py settings for HTTP-based adapter tests."""
    return {
        "record_mode": "none",
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        "filter_headers": ["authorization", "api_key"],
        "decode_compressed_response": True,
    }


@pytest.fixture
async def integration_env(
    integration_infra: object,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Apply env vars and reset asyncpg pool for one data-ingestion integration test."""
    from data_ingestion.writers.postgres_writer import close_pool  # noqa: PLC0415
    from zinc_test import IntegrationInfra  # noqa: PLC0415

    infra: IntegrationInfra = integration_infra  # type: ignore[assignment]

    monkeypatch.setenv("INGEST_DATABASE_URL", infra.database_url)
    monkeypatch.setenv("NATS_URL", infra.nats_url)
    monkeypatch.setenv("MINIO_ENDPOINT", infra.minio_endpoint)
    monkeypatch.setenv("MINIO_ROOT_USER", infra.minio_access_key)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", infra.minio_secret_key)
    monkeypatch.setenv("MINIO_SNAPSHOT_BUCKET", infra.minio_bucket)
    monkeypatch.setenv("FRED_API_KEY", "integration-test-key")
    monkeypatch.setenv("REDIS_URL", infra.redis_url)

    await close_pool()
    yield infra
    await close_pool()
