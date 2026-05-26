"""audit_checkpoints
Revision ID: 0014_audit_checkpoints
Revises: 0013_model_runs_kind
"""

from alembic import op

revision = "0014_audit_checkpoints"
down_revision = "0013_model_runs_kind"

SQL_UP = """
CREATE TABLE theeyebeta.audit_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  checkpoint_id text NOT NULL UNIQUE,
  last_row_id bigint NOT NULL,
  last_row_hash bytea NOT NULL,
  signature bytea NOT NULL,
  signing_ts timestamptz NOT NULL,
  row_count bigint NOT NULL,
  s3_uri text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_checkpoints_signing_ts
  ON theeyebeta.audit_checkpoints(signing_ts DESC);

GRANT SELECT, INSERT ON theeyebeta.audit_checkpoints TO tb_app;
GRANT SELECT ON theeyebeta.audit_checkpoints TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.audit_checkpoints;
"""


def upgrade() -> None:
    """Create audit_checkpoints table for WORM export metadata."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop audit_checkpoints table."""
    op.execute(SQL_DOWN)
