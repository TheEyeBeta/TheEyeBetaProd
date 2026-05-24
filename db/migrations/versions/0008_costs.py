"""costs
Revision ID: 0008_costs
Revises: 0007_backtest_risk
"""
from alembic import op
revision = "0008_costs"
down_revision = "0007_backtest_risk"

SQL_UP = """
CREATE TABLE theeyebeta.model_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES theeyebeta.agent_runs(id),
  provider text NOT NULL,
  model text NOT NULL,
  input_tokens int NOT NULL, output_tokens int NOT NULL,
  cache_read_tokens int DEFAULT 0, cache_write_tokens int DEFAULT 0,
  cost_usd numeric(10,6) NOT NULL,
  latency_ms int,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_model_runs_created ON theeyebeta.model_runs(created_at DESC);

CREATE TABLE theeyebeta.api_costs (
  id bigserial PRIMARY KEY,
  ts date NOT NULL,
  vendor text NOT NULL,
  category text NOT NULL,
  cost_usd numeric(10,4) NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (ts, vendor, category)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.model_runs, theeyebeta.api_costs TO tb_app;
GRANT SELECT ON theeyebeta.model_runs, theeyebeta.api_costs TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.api_costs;
DROP TABLE IF EXISTS theeyebeta.model_runs;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
