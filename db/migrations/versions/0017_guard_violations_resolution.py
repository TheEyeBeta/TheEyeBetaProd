"""guard_violations resolution metadata (resolved_by, resolved_at, note)

Revision ID: 0017_guard_violations_resolution
Revises: 0016_orders_metadata
"""

from alembic import op

revision = "0017_guard_violations_resolution"
down_revision = "0016_orders_metadata"

SQL_UP = """
ALTER TABLE theeyebeta.guard_violations
  ADD COLUMN IF NOT EXISTS resolved_by text,
  ADD COLUMN IF NOT EXISTS resolved_at timestamptz,
  ADD COLUMN IF NOT EXISTS resolution_note text;
"""

SQL_DOWN = """
ALTER TABLE theeyebeta.guard_violations
  DROP COLUMN IF EXISTS resolution_note,
  DROP COLUMN IF EXISTS resolved_at,
  DROP COLUMN IF EXISTS resolved_by;
"""


def upgrade() -> None:
    """Add resolution-tracking columns for the admin guard router."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop resolution-tracking columns."""
    op.execute(SQL_DOWN)
