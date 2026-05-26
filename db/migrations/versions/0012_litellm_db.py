"""litellm_db
Revision ID: 0012_litellm_db
Revises: 0011_data_snapshots_packaged

Creates the ``litellm`` PostgreSQL role and database for the LiteLLM proxy.

Requires ``LITELLM_DB_PASSWORD`` in the environment when running ``alembic upgrade``.
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0012_litellm_db"
down_revision = "0011_data_snapshots_packaged"
branch_labels = None
depends_on = None


def _litellm_password() -> str:
    raw = os.environ.get("LITELLM_DB_PASSWORD", "")
    if not raw:
        msg = "LITELLM_DB_PASSWORD must be set before running migration 0012_litellm_db"
        raise RuntimeError(msg)
    return raw.replace("'", "''")


def upgrade() -> None:
    """Create litellm role and database if they do not exist."""
    password = _litellm_password()
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'litellm') THEN
            CREATE ROLE litellm WITH LOGIN PASSWORD '{password}';
          END IF;
        END
        $$;
        """
    )
    bind = op.get_bind()
    exists = bind.execute(
        text("SELECT 1 FROM pg_database WHERE datname = 'litellm'"),
    ).scalar()
    if not exists:
        op.execute(text("CREATE DATABASE litellm OWNER litellm"))
    op.execute(text("GRANT CONNECT ON DATABASE litellm TO litellm"))


def downgrade() -> None:
    """Drop litellm database and role."""
    bind = op.get_bind()
    exists = bind.execute(
        text("SELECT 1 FROM pg_database WHERE datname = 'litellm'"),
    ).scalar()
    if exists:
        op.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                  FROM pg_stat_activity
                 WHERE datname = 'litellm'
                   AND pid <> pg_backend_pid()
                """
            )
        )
        op.execute(text("DROP DATABASE litellm"))
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'litellm') THEN
            DROP ROLE litellm;
          END IF;
        END
        $$;
        """
    )
