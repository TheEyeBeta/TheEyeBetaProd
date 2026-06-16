"""audit_chain_status

Revision ID: 0030_audit_chain_status
Revises: 0029_audit_worm_policy

Persist scheduled audit hash-chain verification results for ops/pulse.
"""

from alembic import op

revision = "0030_audit_chain_status"
down_revision = "0029_audit_worm_policy"

SQL_UP = """
CREATE TABLE IF NOT EXISTS theeyebeta.audit_chain_status (
  id bigserial PRIMARY KEY,
  verified_at timestamptz NOT NULL DEFAULT now(),
  valid boolean NOT NULL,
  entries_checked bigint NOT NULL DEFAULT 0,
  first_invalid_seq bigint,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_chain_status_verified_at
  ON theeyebeta.audit_chain_status (verified_at DESC);

GRANT SELECT, INSERT ON theeyebeta.audit_chain_status TO tb_app;
GRANT SELECT ON theeyebeta.audit_chain_status TO tb_rnd_readonly;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.audit_chain_status_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.audit_chain_status;
"""


def upgrade() -> None:
    """Create audit_chain_status table for daily verify results."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop audit_chain_status table."""
    op.execute(SQL_DOWN)
