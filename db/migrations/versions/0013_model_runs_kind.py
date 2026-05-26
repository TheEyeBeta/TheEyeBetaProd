"""model_runs_kind
Revision ID: 0013_model_runs_kind
Revises: 0012_litellm_db

Adds ``kind`` to distinguish LLM completions from tool invocations in model_runs.
"""

from alembic import op

revision = "0013_model_runs_kind"
down_revision = "0012_litellm_db"
branch_labels = None
depends_on = None

SQL_UP = """
ALTER TABLE theeyebeta.model_runs
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'completion';
CREATE INDEX IF NOT EXISTS idx_model_runs_kind
  ON theeyebeta.model_runs(kind, created_at DESC);
"""

SQL_DOWN = """
DROP INDEX IF EXISTS theeyebeta.idx_model_runs_kind;
ALTER TABLE theeyebeta.model_runs DROP COLUMN IF EXISTS kind;
"""


def upgrade() -> None:
    """Add model_runs.kind column."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove model_runs.kind column."""
    op.execute(SQL_DOWN)
