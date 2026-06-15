"""market_cap_universe

Revision ID: 0018_market_cap_universe
Revises: 0017_guard_violations_resolution
"""

from alembic import op

revision = "0018_market_cap_universe"
down_revision = "0017_guard_violations_resolution"

SQL_UP = """
CREATE TABLE theeyebeta.market_cap_daily (
  id bigserial PRIMARY KEY,
  symbol text NOT NULL,
  instrument_id bigint REFERENCES theeyebeta.instruments(id),
  as_of_date date NOT NULL,
  market_cap numeric(20, 2) NOT NULL,
  close_price numeric(20, 6),
  shares_outstanding bigint,
  source text NOT NULL DEFAULT 'massive',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (symbol, as_of_date)
);

CREATE INDEX idx_market_cap_daily_date_cap
  ON theeyebeta.market_cap_daily (as_of_date DESC, market_cap DESC);

CREATE INDEX idx_market_cap_daily_instrument_date
  ON theeyebeta.market_cap_daily (instrument_id, as_of_date DESC);

CREATE TABLE theeyebeta.audit_cap_events (
  id bigserial PRIMARY KEY,
  trade_date date NOT NULL,
  symbol text NOT NULL,
  instrument_id bigint REFERENCES theeyebeta.instruments(id),
  event_type text NOT NULL CHECK (event_type IN ('CROSSED_UP', 'CROSSED_DOWN')),
  market_cap numeric(20, 2) NOT NULL,
  prior_market_cap numeric(20, 2),
  action_required text NOT NULL,
  universe_updated boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_cap_events_date_type
  ON theeyebeta.audit_cap_events (trade_date DESC, event_type);

GRANT SELECT, INSERT, UPDATE, DELETE
  ON theeyebeta.market_cap_daily, theeyebeta.audit_cap_events TO tb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.market_cap_daily, theeyebeta.audit_cap_events TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.audit_cap_events;
DROP TABLE IF EXISTS theeyebeta.market_cap_daily;
"""


def upgrade() -> None:
    """Create market-cap snapshot and crossing audit tables."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop market-cap universe tables."""
    op.execute(SQL_DOWN)
