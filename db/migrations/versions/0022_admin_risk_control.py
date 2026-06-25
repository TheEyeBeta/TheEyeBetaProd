"""Admin risk control state, limits overlay, overrides, events

Revision ID: 0022_admin_risk_control
Revises: 0021_admin_trading_control
"""

from alembic import op

revision = "0022_admin_risk_control"
down_revision = "0021_admin_trading_control"

SQL_UP = """
CREATE TABLE theeyebeta.admin_risk_limits (
  id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  version     integer NOT NULL DEFAULT 1,
  limits      jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  text
);

INSERT INTO theeyebeta.admin_risk_limits (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_risk_state (
  id                       smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  trading_locked           boolean NOT NULL DEFAULT false,
  lock_reason              text,
  locked_by                text,
  locked_at                timestamptz,
  last_compute_at          timestamptz,
  last_compute_by          text,
  last_compute_portfolio_id uuid,
  updated_at               timestamptz NOT NULL DEFAULT now()
);

INSERT INTO theeyebeta.admin_risk_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_risk_overrides (
  id            bigserial PRIMARY KEY,
  portfolio_id  uuid,
  check_name    text NOT NULL,
  reason        text NOT NULL,
  actor         text NOT NULL,
  expires_at    timestamptz,
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_risk_overrides_active
  ON theeyebeta.admin_risk_overrides(portfolio_id, check_name)
  WHERE active;

CREATE TABLE theeyebeta.admin_risk_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_risk_events_created
  ON theeyebeta.admin_risk_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_risk_limits TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_risk_state TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_risk_overrides TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_risk_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_risk_overrides_id_seq TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_risk_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_risk_events;
DROP TABLE IF EXISTS theeyebeta.admin_risk_overrides;
DROP TABLE IF EXISTS theeyebeta.admin_risk_state;
DROP TABLE IF EXISTS theeyebeta.admin_risk_limits;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
