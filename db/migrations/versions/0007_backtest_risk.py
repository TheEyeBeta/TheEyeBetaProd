"""backtest_risk
Revision ID: 0007_backtest_risk
Revises: 0006_trading
"""
from alembic import op
revision = "0007_backtest_risk"
down_revision = "0006_trading"

SQL_UP = """
CREATE TABLE theeyebeta.backtest_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id text NOT NULL REFERENCES theeyebeta.strategies(id),
  start_date date NOT NULL, end_date date NOT NULL,
  universe text NOT NULL,
  config jsonb NOT NULL,
  git_sha text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  status text NOT NULL DEFAULT 'running',
  result_blob_uri text
);

CREATE TABLE theeyebeta.backtest_results (
  backtest_id uuid NOT NULL REFERENCES theeyebeta.backtest_runs(id),
  metric text NOT NULL,
  value numeric(20,8) NOT NULL,
  PRIMARY KEY (backtest_id, metric)
);

CREATE TABLE theeyebeta.risk_metrics (
  id bigserial,
  portfolio_id uuid NOT NULL REFERENCES theeyebeta.portfolios(id),
  ts timestamptz NOT NULL,
  var_95 numeric(20,6), cvar_95 numeric(20,6),
  max_drawdown numeric(10,6),
  gross_exposure numeric(20,6), net_exposure numeric(20,6),
  beta_spy numeric(10,6),
  concentration_hhi numeric(10,6),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('theeyebeta.risk_metrics', 'ts', chunk_time_interval => INTERVAL '1 month');

CREATE TABLE theeyebeta.compliance_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id uuid REFERENCES theeyebeta.orders(id),
  portfolio_id uuid REFERENCES theeyebeta.portfolios(id),
  rule_id text NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('pass','warn','block')),
  detail text,
  checked_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_compliance_order ON theeyebeta.compliance_checks(order_id);

-- Close the deferred FK from 0005
ALTER TABLE theeyebeta.proposals
  ADD CONSTRAINT proposals_validation_backtest_fk
  FOREIGN KEY (validation_backtest_id) REFERENCES theeyebeta.backtest_runs(id);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.backtest_runs, theeyebeta.backtest_results,
      theeyebeta.risk_metrics, theeyebeta.compliance_checks TO tb_app;
GRANT SELECT ON theeyebeta.backtest_runs, theeyebeta.backtest_results,
      theeyebeta.risk_metrics, theeyebeta.compliance_checks TO tb_rnd_readonly;
"""

SQL_DOWN = """
ALTER TABLE theeyebeta.proposals DROP CONSTRAINT IF EXISTS proposals_validation_backtest_fk;
DROP TABLE IF EXISTS theeyebeta.compliance_checks;
DROP TABLE IF EXISTS theeyebeta.risk_metrics;
DROP TABLE IF EXISTS theeyebeta.backtest_results;
DROP TABLE IF EXISTS theeyebeta.backtest_runs;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
