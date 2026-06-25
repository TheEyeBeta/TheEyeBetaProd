"""Admin trading control state, events, and live approval tokens

Revision ID: 0021_admin_trading_control
Revises: 0020_admin_service_actions
"""

from alembic import op

revision = "0021_admin_trading_control"
down_revision = "0020_admin_service_actions"

SQL_UP = """
CREATE TABLE theeyebeta.admin_trading_state (
  id                    smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  live_trading_enabled  boolean NOT NULL DEFAULT false,
  emergency_halt        boolean NOT NULL DEFAULT false,
  broker_mode           text NOT NULL DEFAULT 'paper'
                        CHECK (broker_mode IN ('paper', 'live')),
  last_halt_reason      text,
  last_halt_at          timestamptz,
  last_halt_by          text,
  last_resume_reason    text,
  last_resume_at        timestamptz,
  last_resume_by        text,
  last_operator         text,
  updated_at            timestamptz NOT NULL DEFAULT now()
);

INSERT INTO theeyebeta.admin_trading_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE theeyebeta.admin_live_approval_tokens (
  token_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash    text NOT NULL UNIQUE,
  issued_by     text NOT NULL,
  issued_at     timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  consumed_at   timestamptz,
  consumed_by   text,
  purpose       text NOT NULL DEFAULT 'enable_live_trading'
);

CREATE INDEX idx_admin_live_approval_tokens_active
  ON theeyebeta.admin_live_approval_tokens(expires_at)
  WHERE consumed_at IS NULL;

CREATE TABLE theeyebeta.admin_trading_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_trading_events_created
  ON theeyebeta.admin_trading_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_trading_state TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_live_approval_tokens TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_trading_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_trading_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_trading_events;
DROP TABLE IF EXISTS theeyebeta.admin_live_approval_tokens;
DROP TABLE IF EXISTS theeyebeta.admin_trading_state;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
