"""Admin compliance control state, rules overlay, exceptions, legal holds, events

Revision ID: 0023_admin_compliance_control
Revises: 0022_admin_risk_control
"""

from alembic import op

revision = "0023_admin_compliance_control"
down_revision = "0022_admin_risk_control"

SQL_UP = """
CREATE TABLE theeyebeta.admin_compliance_rules (
  id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  version     integer NOT NULL DEFAULT 1,
  rules       jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  text
);

INSERT INTO theeyebeta.admin_compliance_rules (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_compliance_state (
  id                       smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_recheck_at          timestamptz,
  last_recheck_by          text,
  last_recheck_portfolio_id uuid,
  updated_at               timestamptz NOT NULL DEFAULT now()
);

INSERT INTO theeyebeta.admin_compliance_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_compliance_overrides (
  id            bigserial PRIMARY KEY,
  portfolio_id  uuid,
  rule_id       text NOT NULL,
  reason        text NOT NULL,
  actor         text NOT NULL,
  expires_at    timestamptz,
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_compliance_overrides_active
  ON theeyebeta.admin_compliance_overrides(portfolio_id, rule_id)
  WHERE active;

CREATE TABLE theeyebeta.admin_compliance_exceptions (
  id            bigserial PRIMARY KEY,
  portfolio_id  uuid,
  rule_id       text NOT NULL,
  reason        text NOT NULL,
  actor         text NOT NULL,
  expires_at    timestamptz,
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_compliance_exceptions_active
  ON theeyebeta.admin_compliance_exceptions(portfolio_id, rule_id)
  WHERE active;

CREATE TABLE theeyebeta.admin_legal_holds (
  id            bigserial PRIMARY KEY,
  entity_type   text NOT NULL CHECK (entity_type IN ('portfolio', 'account', 'instrument')),
  entity_id     text NOT NULL,
  reason        text NOT NULL,
  placed_by     text NOT NULL,
  placed_at     timestamptz NOT NULL DEFAULT now(),
  released_by   text,
  released_at   timestamptz,
  active        boolean NOT NULL DEFAULT true
);

CREATE INDEX idx_admin_legal_holds_active
  ON theeyebeta.admin_legal_holds(entity_type, entity_id)
  WHERE active;

CREATE TABLE theeyebeta.admin_compliance_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_compliance_events_created
  ON theeyebeta.admin_compliance_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_compliance_rules TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_compliance_state TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_compliance_overrides TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_compliance_exceptions TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_legal_holds TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_compliance_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_compliance_overrides_id_seq TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_compliance_exceptions_id_seq TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_legal_holds_id_seq TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_compliance_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_compliance_events;
DROP TABLE IF EXISTS theeyebeta.admin_legal_holds;
DROP TABLE IF EXISTS theeyebeta.admin_compliance_exceptions;
DROP TABLE IF EXISTS theeyebeta.admin_compliance_overrides;
DROP TABLE IF EXISTS theeyebeta.admin_compliance_state;
DROP TABLE IF EXISTS theeyebeta.admin_compliance_rules;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
