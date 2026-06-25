"""Admin command console run history

Revision ID: 0027_admin_command_control
Revises: 0026_admin_intelligence_control
"""

from alembic import op

revision = "0027_admin_command_control"
down_revision = "0026_admin_intelligence_control"

SQL_UP = """
CREATE TABLE theeyebeta.admin_command_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  command_id      text NOT NULL,
  command_text    text NOT NULL,
  actor           text NOT NULL,
  reason          text,
  status          text NOT NULL
    CHECK (status IN ('preview','running','succeeded','failed','rejected')),
  preview         jsonb,
  result          jsonb NOT NULL DEFAULT '{}'::jsonb,
  backend_route   text NOT NULL,
  audit_category  text NOT NULL,
  error           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  completed_at    timestamptz
);

CREATE INDEX idx_admin_command_runs_created
  ON theeyebeta.admin_command_runs(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_command_runs TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_command_runs;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
