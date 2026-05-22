"""Fixtures for smoke tests (require running infra via `make up`)."""

from __future__ import annotations

import os

import psycopg
import pytest


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://zinc:zinc_dev@localhost:5432/zinc",
)


@pytest.fixture(scope="session")
def db_conn():
    """Open a single synchronous psycopg connection for the test session.

    The connection is rolled back and closed after all smoke tests complete.
    """
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        yield conn
        conn.rollback()
