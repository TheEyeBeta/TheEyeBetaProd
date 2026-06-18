"""audit_checkpoints_select_policy

Revision ID: 0034_audit_checkpoints_select_policy
Revises: 0033_agent_reporting

Allow application reads of append-only audit checkpoint metadata under RLS.
"""

from alembic import op

revision = "0034_audit_checkpoints_select_policy"
down_revision = "0033_agent_reporting"

SQL_UP = """
GRANT SELECT ON theeyebeta.audit_checkpoints TO tb_app;
GRANT SELECT ON theeyebeta.audit_checkpoints TO tb_rnd_readonly;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_policies
         WHERE schemaname = 'theeyebeta'
           AND tablename = 'audit_checkpoints'
           AND policyname = 'audit_checkpoints_select_all'
    ) THEN
        CREATE POLICY audit_checkpoints_select_all
            ON theeyebeta.audit_checkpoints
            FOR SELECT
            USING (true);
    END IF;
END $$;
"""

SQL_DOWN = """
DROP POLICY IF EXISTS audit_checkpoints_select_all
    ON theeyebeta.audit_checkpoints;
"""


def upgrade() -> None:
    """Allow tb_app and read-only roles to see checkpoint rows."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove checkpoint SELECT RLS policy."""
    op.execute(SQL_DOWN)
