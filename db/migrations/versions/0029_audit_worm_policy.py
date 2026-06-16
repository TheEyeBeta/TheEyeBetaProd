"""audit_worm_policy

Revision ID: 0029_audit_worm_policy
Revises: 0028_totp_mfa

Append-only RLS on audit_checkpoints; dedicated audit_writer role.
"""

from alembic import op

revision = "0029_audit_worm_policy"
down_revision = "0028_totp_mfa"

SQL_UP = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theeyebeta_audit_writer') THEN
    CREATE ROLE theeyebeta_audit_writer NOLOGIN;
  END IF;
END
$$;

ALTER TABLE theeyebeta.audit_checkpoints ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_append_only ON theeyebeta.audit_checkpoints;
DROP POLICY IF EXISTS audit_no_update ON theeyebeta.audit_checkpoints;
DROP POLICY IF EXISTS audit_no_delete ON theeyebeta.audit_checkpoints;

CREATE POLICY audit_append_only ON theeyebeta.audit_checkpoints
  FOR INSERT TO theeyebeta WITH CHECK (true);
CREATE POLICY audit_no_update ON theeyebeta.audit_checkpoints
  FOR UPDATE TO theeyebeta USING (false);
CREATE POLICY audit_no_delete ON theeyebeta.audit_checkpoints
  FOR DELETE TO theeyebeta USING (false);

REVOKE INSERT ON theeyebeta.audit_checkpoints FROM theeyebeta;
GRANT INSERT ON theeyebeta.audit_checkpoints TO theeyebeta_audit_writer;

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

DROP POLICY IF EXISTS audit_append_only ON theeyebeta.audit_checkpoints;
DROP POLICY IF EXISTS audit_no_update ON theeyebeta.audit_checkpoints;
DROP POLICY IF EXISTS audit_no_delete ON theeyebeta.audit_checkpoints;

ALTER TABLE theeyebeta.audit_checkpoints DISABLE ROW LEVEL SECURITY;

GRANT INSERT ON theeyebeta.audit_checkpoints TO theeyebeta;

DROP ROLE IF EXISTS theeyebeta_audit_writer;
"""


def upgrade() -> None:
    """Enable WORM policy on audit_checkpoints and add chain status table."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Revert WORM policy and drop chain status table."""
    op.execute(SQL_DOWN)
