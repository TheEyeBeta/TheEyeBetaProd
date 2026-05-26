"""Integration infrastructure helpers: dataclass, DB bootstrap, DSN utilities."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg

_REPO_ROOT = Path(__file__).resolve().parents[4]  # libs/zinc_test/src/zinc_test/_infra.py → root
_BOOTSTRAP_SQL = _REPO_ROOT / "services" / "data_ingestion" / "tests" / "sql" / "bootstrap.sql"
_SEED_INSTRUMENT_SQL = (
    _REPO_ROOT / "services" / "data_ingestion" / "tests" / "sql" / "seed_us_instrument.sql"
)
_DB_ALEMBIC_INI = _REPO_ROOT / "db" / "alembic.ini"
_SEEDS_SCRIPT = _REPO_ROOT / "db" / "seeds" / "agents.py"


@dataclass(frozen=True)
class IntegrationInfra:
    """Connection endpoints for integration tests."""

    postgres_admin_url: str
    database_url: str
    redis_url: str
    nats_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str


def _normalize_psycopg_dsn(dsn: str) -> str:
    """Strip SQLAlchemy driver suffixes so psycopg.connect accepts the URL."""
    return (
        dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+asyncpg://", "postgresql://", 1)
    )


def _to_asyncpg(dsn: str) -> str:
    """Convert a plain postgresql:// URL to postgresql+asyncpg://."""
    clean = _normalize_psycopg_dsn(dsn)
    return clean.replace("postgresql://", "postgresql+asyncpg://", 1)


def _run_sql_file(dsn: str, path: Path) -> None:
    """Execute a SQL file against the given connection URL."""
    sql = path.read_text(encoding="utf-8")
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(sql)


def app_dsn_from_admin(admin_dsn: str) -> str:
    """Build the tb_app application URL from the admin connection URL."""
    parsed = urlparse(admin_dsn)
    tb_app = parsed._replace(username="tb_app", password="tb_app_test")  # noqa: S106
    plain = urlunparse(tb_app)
    return _normalize_psycopg_dsn(plain)


# Keep legacy alias so existing conftest.py files still import successfully
ingest_dsn_from_admin = app_dsn_from_admin


def bootstrap_database(admin_dsn: str) -> None:
    """Create extensions/schema/roles, run Alembic migrations, seed one US instrument."""
    clean = _normalize_psycopg_dsn(admin_dsn)
    _run_sql_file(clean, _BOOTSTRAP_SQL)

    if _DB_ALEMBIC_INI.exists():
        env = os.environ.copy()
        env["DATABASE_URL"] = _to_asyncpg(clean)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_DB_ALEMBIC_INI.parent,
            check=True,
            env=env,
        )

    _run_sql_file(clean, _SEED_INSTRUMENT_SQL)


def seed_agents(admin_dsn: str) -> None:
    """Upsert the three market agents from db/seeds/agents.py."""
    if not _SEEDS_SCRIPT.exists():
        return
    env = os.environ.copy()
    env["DATABASE_URL"] = _normalize_psycopg_dsn(admin_dsn)
    subprocess.run(
        [sys.executable, str(_SEEDS_SCRIPT)],
        check=True,
        env=env,
    )


def docker_available() -> bool:
    """Return True when the Docker daemon accepts API calls."""
    try:
        import docker  # noqa: PLC0415

        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001
        return False
