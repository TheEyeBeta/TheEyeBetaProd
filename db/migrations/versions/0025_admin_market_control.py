"""Admin market data control state and operator events

Revision ID: 0025_admin_market_control
Revises: 0024_admin_blotter_control
"""

from alembic import op

revision = "0025_admin_market_control"
down_revision = "0024_admin_blotter_control"

SQL_UP = """
CREATE TABLE theeyebeta.admin_market_state (
  id                       smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_backfill_at         timestamptz,
  last_backfill_by         text,
  last_snapshot_build_at   timestamptz,
  last_snapshot_build_by   text,
  updated_at               timestamptz NOT NULL DEFAULT now()
);

INSERT INTO theeyebeta.admin_market_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_market_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_market_events_created
  ON theeyebeta.admin_market_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_market_state TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_market_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_market_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_market_events;
DROP TABLE IF EXISTS theeyebeta.admin_market_state;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
