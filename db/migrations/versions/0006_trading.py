"""trading
Revision ID: 0006_trading
Revises: 0005_two_loop
"""
from alembic import op
revision = "0006_trading"
down_revision = "0005_two_loop"

SQL_UP = """
CREATE TABLE theeyebeta.accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id text NOT NULL UNIQUE,
  broker text NOT NULL,
  mode text NOT NULL CHECK (mode IN ('paper','live')),
  base_currency char(3) NOT NULL DEFAULT 'USD',
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.portfolios (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES theeyebeta.accounts(id),
  name text NOT NULL,
  mandate jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.strategies (
  id text PRIMARY KEY,
  name text NOT NULL,
  description text,
  config jsonb NOT NULL,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE theeyebeta.signals (
  id bigserial,
  strategy_id text NOT NULL REFERENCES theeyebeta.strategies(id),
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  ts timestamptz NOT NULL,
  side text NOT NULL CHECK (side IN ('long','short','flat')),
  strength numeric(6,4),
  features jsonb NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('theeyebeta.signals', 'ts', chunk_time_interval => INTERVAL '1 month');

CREATE TABLE theeyebeta.orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_order_id text NOT NULL UNIQUE,
  broker_order_id text,
  portfolio_id uuid NOT NULL REFERENCES theeyebeta.portfolios(id),
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  decision_id uuid REFERENCES theeyebeta.agent_decisions(id),
  side text NOT NULL CHECK (side IN ('buy','sell')),
  order_type text NOT NULL CHECK (order_type IN ('market','limit','stop','stop_limit','trailing_stop')),
  qty numeric(20,6) NOT NULL,
  limit_price numeric(18,6),
  stop_price numeric(18,6),
  time_in_force text NOT NULL DEFAULT 'day',
  status text NOT NULL DEFAULT 'pending_approval'
    CHECK (status IN ('pending_approval','approved','submitted','accepted','partially_filled',
                      'filled','cancelled','rejected','expired')),
  approved_by text,
  approved_at timestamptz,
  submitted_at timestamptz,
  filled_qty numeric(20,6) NOT NULL DEFAULT 0,
  avg_fill_price numeric(18,6),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_portfolio_status ON theeyebeta.orders(portfolio_id, status);
CREATE INDEX idx_orders_inst_created ON theeyebeta.orders(instrument_id, created_at DESC);

CREATE TABLE theeyebeta.executions (
  id bigserial PRIMARY KEY,
  order_id uuid NOT NULL REFERENCES theeyebeta.orders(id),
  ts timestamptz NOT NULL,
  qty numeric(20,6) NOT NULL,
  price numeric(18,6) NOT NULL,
  commission numeric(12,6) NOT NULL DEFAULT 0,
  liquidity_flag text,
  raw jsonb NOT NULL
);

CREATE TABLE theeyebeta.positions (
  id bigserial PRIMARY KEY,
  portfolio_id uuid NOT NULL REFERENCES theeyebeta.portfolios(id),
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  qty numeric(20,6) NOT NULL,
  avg_entry_price numeric(18,6) NOT NULL,
  market_value numeric(20,6),
  unrealized_pnl numeric(20,6),
  realized_pnl numeric(20,6),
  opened_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (portfolio_id, instrument_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.accounts, theeyebeta.portfolios,
      theeyebeta.strategies, theeyebeta.signals, theeyebeta.orders, theeyebeta.executions,
      theeyebeta.positions TO tb_app;
GRANT SELECT ON theeyebeta.accounts, theeyebeta.portfolios, theeyebeta.strategies,
      theeyebeta.signals, theeyebeta.orders, theeyebeta.executions, theeyebeta.positions TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.positions;
DROP TABLE IF EXISTS theeyebeta.executions;
DROP TABLE IF EXISTS theeyebeta.orders;
DROP TABLE IF EXISTS theeyebeta.signals;
DROP TABLE IF EXISTS theeyebeta.strategies;
DROP TABLE IF EXISTS theeyebeta.portfolios;
DROP TABLE IF EXISTS theeyebeta.accounts;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
