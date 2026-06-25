"""Operator action history for allowlisted services

Revision ID: 0020_admin_service_actions
Revises: 0019_worker_control_state
"""

from alembic import op

revision = "0020_admin_service_actions"
down_revision = "0019_worker_control_state"

SQL_UP = """
CREATE TABLE theeyebeta.admin_service_actions (
  id            bigserial PRIMARY KEY,
  service_name  text NOT NULL,
  action        text NOT NULL,
  actor         text NOT NULL,
  reason        text,
  status        text NOT NULL,
  message       text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_service_actions_service_created
  ON theeyebeta.admin_service_actions(service_name, created_at DESC);

GRANT SELECT, INSERT ON theeyebeta.admin_service_actions TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_service_actions_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_service_actions;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
