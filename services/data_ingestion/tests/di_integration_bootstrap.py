"""Helpers to bootstrap a testcontainers Postgres for integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class IntegrationInfra:
    """Connection endpoints for integration tests."""

    ingest_database_url: str
    nats_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    redis_url: str
SQL_DIR = Path(__file__).resolve().parent / "sql"


def _normalize_psycopg_dsn(dsn: str) -> str:
    """Strip SQLAlchemy driver suffixes for psycopg.connect."""
    return dsn.replace("postgresql+psycopg2://", "postgresql://", 1)


def _run_sql_file(dsn: str, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(sql)


def bootstrap_database(admin_dsn: str) -> None:
    """Create extensions, schema, roles, run migrations, and seed US instrument."""
    admin_dsn = _normalize_psycopg_dsn(admin_dsn)
    _run_sql_file(admin_dsn, SQL_DIR / "bootstrap.sql")

    async_url = _to_asyncpg(admin_dsn)
    env = os.environ.copy()
    env["DATABASE_URL"] = async_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT / "db",
        check=True,
        env=env,
    )

    _run_sql_file(admin_dsn, SQL_DIR / "seed_us_instrument.sql")


def ingest_dsn_from_admin(admin_dsn: str) -> str:
    """Build tb_app INGEST_DATABASE_URL from the admin connection URL."""
    parsed = urlparse(admin_dsn)
    tb_app = parsed._replace(
        username="tb_app",
        password="tb_app_test",  # noqa: S106
    )
    plain = urlunparse(tb_app)
    return plain.replace("postgresql+psycopg2://", "postgresql://")


def _to_asyncpg(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg2://"):
        return dsn.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn
