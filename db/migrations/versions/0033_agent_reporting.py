"""agent_reporting

Revision ID: 0033_agent_reporting
Revises: 0032_nyse_nasdaq_portfolios

Add chain-of-command ``reports_to`` on agents and ``agent_reports`` for operator briefings.
"""

from alembic import op

revision = "0033_agent_reporting"
down_revision = "0032_nyse_nasdaq_portfolios"

SQL_UP = """
ALTER TABLE theeyebeta.agents
  ADD COLUMN IF NOT EXISTS reports_to text REFERENCES theeyebeta.agents(id);

CREATE INDEX IF NOT EXISTS idx_agents_reports_to ON theeyebeta.agents(reports_to);

CREATE TABLE theeyebeta.agent_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id text NOT NULL REFERENCES theeyebeta.agents(id),
  audience text NOT NULL DEFAULT 'operator',
  run_id uuid REFERENCES theeyebeta.agent_runs(id),
  report_type text NOT NULL DEFAULT 'briefing'
    CHECK (report_type IN ('briefing', 'escalation', 'rollup', 'trade_synthesis')),
  period_start timestamptz,
  period_end timestamptz,
  summary text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'published'
    CHECK (status IN ('draft', 'published', 'superseded')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_reports_audience_created
  ON theeyebeta.agent_reports(audience, created_at DESC);

CREATE INDEX idx_agent_reports_agent_created
  ON theeyebeta.agent_reports(agent_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.agent_reports TO tb_app;
GRANT SELECT ON theeyebeta.agent_reports TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.agent_reports;
ALTER TABLE theeyebeta.agents DROP COLUMN IF EXISTS reports_to;
"""


def upgrade() -> None:
    """Add reporting chain columns and operator briefing storage."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove agent reporting tables and hierarchy column."""
    op.execute(SQL_DOWN)
