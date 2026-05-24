"""agents
Revision ID: 0004_agents
Revises: 0003_fundamentals_macro_news
"""
from alembic import op
revision = "0004_agents"
down_revision = "0003_fundamentals_macro_news"

SQL_UP = """
CREATE TABLE theeyebeta.agents (
  id text PRIMARY KEY,
  department text NOT NULL,
  role text NOT NULL,
  model_default text NOT NULL,
  model_fallback text,
  constitution_path text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id text NOT NULL REFERENCES theeyebeta.agents(id),
  triggered_by text NOT NULL,
  parent_run_id uuid REFERENCES theeyebeta.agent_runs(id),
  snapshot_id uuid,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  status text NOT NULL DEFAULT 'running'
    CHECK (status IN ('running','succeeded','failed','timeout','cancelled')),
  total_input_tokens int,
  total_output_tokens int,
  total_cost_usd numeric(10,6),
  error text
);
CREATE INDEX idx_agent_runs_agent_started ON theeyebeta.agent_runs(agent_id, started_at DESC);

CREATE TABLE theeyebeta.agent_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES theeyebeta.agent_runs(id),
  instrument_id bigint REFERENCES theeyebeta.instruments(id),
  market text,
  decision text NOT NULL CHECK (decision IN ('BUY','SELL','HOLD','REDUCE','EXIT','OBSERVE')),
  confidence numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  rationale text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  proposed_qty numeric(20,6),
  proposed_price numeric(18,6),
  horizon_days int,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_decisions_inst ON theeyebeta.agent_decisions(instrument_id, created_at DESC);

CREATE TABLE theeyebeta.agent_messages (
  id bigserial PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES theeyebeta.agent_runs(id),
  from_agent text NOT NULL,
  to_agent text,
  role text NOT NULL CHECK (role IN ('argument','rebuttal','question','answer','summary')),
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_msgs_run ON theeyebeta.agent_messages(run_id, created_at);

CREATE TABLE theeyebeta.agent_memory (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id text NOT NULL REFERENCES theeyebeta.agents(id),
  kind text NOT NULL,
  content text NOT NULL,
  embedding vector(1536) NOT NULL,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_mem_hnsw ON theeyebeta.agent_memory
  USING hnsw (embedding vector_cosine_ops);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.agents, theeyebeta.agent_runs,
      theeyebeta.agent_decisions, theeyebeta.agent_messages, theeyebeta.agent_memory TO tb_app;
GRANT SELECT ON theeyebeta.agents, theeyebeta.agent_runs, theeyebeta.agent_decisions,
      theeyebeta.agent_messages, theeyebeta.agent_memory TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.agent_memory;
DROP TABLE IF EXISTS theeyebeta.agent_messages;
DROP TABLE IF EXISTS theeyebeta.agent_decisions;
DROP TABLE IF EXISTS theeyebeta.agent_runs;
DROP TABLE IF EXISTS theeyebeta.agents;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
