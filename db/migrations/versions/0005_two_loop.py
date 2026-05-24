"""two_loop_enforcement
Revision ID: 0005_two_loop
Revises: 0004_agents
"""
from alembic import op
revision = "0005_two_loop"
down_revision = "0004_agents"

SQL_UP = """
CREATE TABLE theeyebeta.guard_violations (
  id            bigserial PRIMARY KEY,
  ts            timestamptz NOT NULL DEFAULT now(),
  run_id        uuid NOT NULL REFERENCES theeyebeta.agent_runs(id),
  agent_id      text NOT NULL REFERENCES theeyebeta.agents(id),
  violation_type text NOT NULL CHECK (violation_type IN (
    'schema','confidence_range','missing_evidence','tool_whitelist',
    'creative_content','mandate_boundary','forbidden_target')),
  severity      text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  detail        jsonb NOT NULL,
  resolution    text NOT NULL CHECK (resolution IN ('retry','fallback','escalate','reject')),
  resolved      boolean NOT NULL DEFAULT false
);
CREATE INDEX idx_guard_violations_agent_ts ON theeyebeta.guard_violations(agent_id, ts DESC);
CREATE INDEX idx_guard_violations_unresolved ON theeyebeta.guard_violations(resolved) WHERE NOT resolved;

CREATE TABLE theeyebeta.proposals (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposed_by       text NOT NULL,
  run_id            uuid REFERENCES theeyebeta.agent_runs(id),
  category          text NOT NULL CHECK (category IN (
    'strategy_param','agent_constitution','risk_rule',
    'compliance_rule_nonregulatory','new_strategy','architecture')),
  target            text NOT NULL,
  current_value     jsonb NOT NULL,
  proposed_value    jsonb NOT NULL,
  rationale         text NOT NULL,
  evidence          jsonb NOT NULL,
  estimated_impact  jsonb,
  status            text NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending','approved','rejected','superseded','applied')),
  reviewed_by       text,
  reviewed_at       timestamptz,
  review_notes      text,
  validation_backtest_id uuid,  -- FK added in migration 0007 once backtest_runs exists
  applied_at        timestamptz,
  applied_commit_sha text,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_proposals_status_created ON theeyebeta.proposals(status, created_at DESC);
CREATE INDEX idx_proposals_target ON theeyebeta.proposals(target);
CREATE INDEX idx_proposals_category ON theeyebeta.proposals(category);

CREATE OR REPLACE FUNCTION theeyebeta.expire_stale_proposals() RETURNS void AS $f$
  UPDATE theeyebeta.proposals SET status = 'superseded'
   WHERE status = 'pending' AND created_at < now() - INTERVAL '14 days';
$f$ LANGUAGE sql;

-- Sanitized audit view (audit_log table itself is created in 0009)
-- Define a placeholder view that 0009 will replace once audit_log exists.
CREATE TABLE theeyebeta._audit_summary_placeholder (id bigint);  -- temporary; dropped in 0009

-- Grants for tb_app on the two new tables
GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.guard_violations, theeyebeta.proposals TO tb_app;

-- Grants for tb_rnd_readonly: SELECT on guard_violations + INSERT/SELECT on proposals only
GRANT SELECT ON theeyebeta.guard_violations TO tb_rnd_readonly;
GRANT INSERT, SELECT ON theeyebeta.proposals TO tb_rnd_readonly;
REVOKE UPDATE, DELETE ON theeyebeta.proposals FROM tb_rnd_readonly;

-- Block tb_rnd_readonly from picking up grants on future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA theeyebeta REVOKE INSERT, UPDATE, DELETE ON TABLES FROM tb_rnd_readonly;
"""

SQL_DOWN = """
DROP FUNCTION IF EXISTS theeyebeta.expire_stale_proposals();
DROP TABLE IF EXISTS theeyebeta._audit_summary_placeholder;
DROP TABLE IF EXISTS theeyebeta.proposals;
DROP TABLE IF EXISTS theeyebeta.guard_violations;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
