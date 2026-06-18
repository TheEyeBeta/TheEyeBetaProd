"""zinc_fund_tracking

Revision ID: 0031_zinc_fund_tracking
Revises: 0030_audit_chain_status

Register ZINC INVESTMENTS as a named paper sub-account and portfolio,
and create a TimescaleDB hypertable for 15-minute fund value snapshots.
"""

from alembic import op

revision = "0031_zinc_fund_tracking"
down_revision = "0030_audit_chain_status"

SQL_UP = """
-- ZINC INVESTMENTS paper sub-account (Alpaca account PA3YHM9XSMXP)
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode, metadata)
VALUES (
  'c30e8400-e29b-41d4-a716-446655440003',
  'PA3YHM9XSMXP',
  'alpaca',
  'paper',
  '{"display_name": "ZINC INVESTMENTS", "sub_account": true}'
)
ON CONFLICT (external_id) DO NOTHING;

-- Portfolio linked to the ZINC INVESTMENTS account
INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
VALUES (
  'c40e8400-e29b-41d4-a716-446655440004',
  'c30e8400-e29b-41d4-a716-446655440003',
  'zinc-investments',
  '{
    "strategy": "mega_cap_tech_4x",
    "leverage": 4,
    "description": "Top 10 US tech companies by market cap, 4x leveraged paper portfolio",
    "universe": ["NVDA","GOOGL","AAPL","MSFT","AMZN","AVGO","TSLA","META","MU","AMD"]
  }'
)
ON CONFLICT (id) DO NOTHING;

-- 15-minute fund value snapshots (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS theeyebeta.paper_fund_snapshots (
  snapshotted_at  timestamptz   NOT NULL DEFAULT now(),
  portfolio_id    uuid          NOT NULL REFERENCES theeyebeta.portfolios(id) ON DELETE RESTRICT,
  cash            numeric(20,6) NOT NULL DEFAULT 0,
  market_value    numeric(20,6) NOT NULL DEFAULT 0,
  total_value     numeric(20,6) NOT NULL DEFAULT 0,
  unrealized_pnl  numeric(20,6) NOT NULL DEFAULT 0,
  positions_count smallint      NOT NULL DEFAULT 0,
  positions       jsonb         NOT NULL DEFAULT '[]',
  PRIMARY KEY (portfolio_id, snapshotted_at)
);

SELECT create_hypertable(
  'theeyebeta.paper_fund_snapshots',
  'snapshotted_at',
  if_not_exists     => TRUE,
  chunk_time_interval => INTERVAL '1 week'
);

CREATE INDEX IF NOT EXISTS idx_paper_fund_snapshots_portfolio_time
  ON theeyebeta.paper_fund_snapshots (portfolio_id, snapshotted_at DESC);

GRANT SELECT, INSERT ON theeyebeta.paper_fund_snapshots TO tb_app;
GRANT SELECT            ON theeyebeta.paper_fund_snapshots TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.paper_fund_snapshots;
DELETE FROM theeyebeta.portfolios WHERE id = 'c40e8400-e29b-41d4-a716-446655440004';
DELETE FROM theeyebeta.accounts   WHERE id = 'c30e8400-e29b-41d4-a716-446655440003';
"""


def upgrade() -> None:
    """Create zinc-investments account, portfolio, and fund snapshot hypertable."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop fund snapshot table and zinc account/portfolio seed rows."""
    op.execute(SQL_DOWN)
