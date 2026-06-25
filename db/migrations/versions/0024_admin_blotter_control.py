"""Admin trading blotter state and operator events

Revision ID: 0024_admin_blotter_control
Revises: 0023_admin_compliance_control
"""

from alembic import op

revision = "0024_admin_blotter_control"
down_revision = "0023_admin_compliance_control"

SQL_UP = """
CREATE TABLE theeyebeta.admin_blotter_state (
  id                       smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_broker_test_at      timestamptz,
  last_broker_test_by      text,
  last_broker_test_ok      boolean,
  last_reconciliation_at   timestamptz,
  last_reconciliation_by   text,
  last_drift_count         integer NOT NULL DEFAULT 0,
  updated_at               timestamptz NOT NULL DEFAULT now()
);

INSERT INTO theeyebeta.admin_blotter_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_blotter_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_blotter_events_created
  ON theeyebeta.admin_blotter_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_blotter_state TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_blotter_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_blotter_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_blotter_events;
DROP TABLE IF EXISTS theeyebeta.admin_blotter_state;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
