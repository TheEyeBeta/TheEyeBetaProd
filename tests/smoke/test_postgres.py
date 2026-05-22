"""Smoke test: verify Postgres is reachable and the expected extensions are present."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.smoke


def test_postgres_connection(db_conn):
    """psycopg can connect and execute a trivial query."""
    cur = db_conn.cursor()
    cur.execute("SELECT 1 AS value")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 1


def test_postgres_version(db_conn):
    """Server is PostgreSQL 17."""
    cur = db_conn.cursor()
    cur.execute("SELECT current_setting('server_version_num')::int")
    version_num = cur.fetchone()[0]
    assert version_num >= 170000, f"Expected PG17+, got version_num={version_num}"


def test_timescaledb_extension(db_conn):
    """TimescaleDB extension is installed."""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT extname FROM pg_extension WHERE extname = 'timescaledb'"
    )
    row = cur.fetchone()
    assert row is not None, "timescaledb extension not found"


def test_pgvector_extension(db_conn):
    """pgvector extension is available (may not yet be created in zinc DB)."""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT name FROM pg_available_extensions WHERE name = 'vector'"
    )
    row = cur.fetchone()
    assert row is not None, "pgvector extension not available on this server"


def test_postgres_database_name(db_conn):
    """Connected to the expected database."""
    cur = db_conn.cursor()
    cur.execute("SELECT current_database()")
    db_name = cur.fetchone()[0]
    assert db_name == "zinc", f"Expected database 'zinc', got '{db_name}'"
