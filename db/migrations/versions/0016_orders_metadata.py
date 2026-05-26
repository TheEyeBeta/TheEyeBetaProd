"""orders metadata jsonb for admin reject reasons

Revision ID: 0016_orders_metadata
Revises: 0015_rnd_readonly_views
"""
from alembic import op

revision = "0016_orders_metadata"
down_revision = "0015_rnd_readonly_views"

SQL_UP = """
ALTER TABLE theeyebeta.orders
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
"""

SQL_DOWN = """
ALTER TABLE theeyebeta.orders DROP COLUMN IF EXISTS metadata;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
