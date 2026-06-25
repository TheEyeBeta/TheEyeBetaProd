"""Admin intelligence control — agents, costs, briefings, operator events

Revision ID: 0026_admin_intelligence_control
Revises: 0025_admin_market_control
"""

from alembic import op

revision = "0026_admin_intelligence_control"
down_revision = "0025_admin_market_control"

SQL_UP = """
ALTER TABLE theeyebeta.proposals DROP CONSTRAINT IF EXISTS proposals_status_check;
ALTER TABLE theeyebeta.proposals ADD CONSTRAINT proposals_status_check
  CHECK (status IN ('pending','approved','rejected','superseded','applied','deferred'));

CREATE TABLE theeyebeta.admin_agent_control (
  agent_id    text PRIMARY KEY REFERENCES theeyebeta.agents(id),
  paused      boolean NOT NULL DEFAULT false,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  text
);

CREATE TABLE theeyebeta.admin_agent_versions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        text NOT NULL REFERENCES theeyebeta.agents(id),
  label           text NOT NULL,
  constitution_path text NOT NULL,
  content_hash    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  created_by      text NOT NULL
);
CREATE INDEX idx_admin_agent_versions_agent
  ON theeyebeta.admin_agent_versions(agent_id, created_at DESC);

CREATE TABLE theeyebeta.admin_cost_state (
  id                    smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  kill_switch_active    boolean NOT NULL DEFAULT false,
  kill_switch_reason    text,
  kill_switch_by        text,
  kill_switch_at        timestamptz,
  updated_at            timestamptz NOT NULL DEFAULT now()
);
INSERT INTO theeyebeta.admin_cost_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE theeyebeta.admin_cost_budgets (
  id                  serial PRIMARY KEY,
  scope               text NOT NULL UNIQUE,
  monthly_limit_usd   numeric(12,2) NOT NULL,
  warn_threshold_pct  numeric(5,2) NOT NULL DEFAULT 80.0,
  updated_at          timestamptz NOT NULL DEFAULT now(),
  updated_by          text
);

INSERT INTO theeyebeta.admin_cost_budgets (scope, monthly_limit_usd)
VALUES
  ('global', 5000.00),
  ('agents', 3000.00),
  ('api_vendors', 2000.00)
ON CONFLICT (scope) DO NOTHING;

CREATE TABLE theeyebeta.admin_briefings (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title         text NOT NULL,
  status        text NOT NULL DEFAULT 'ready'
    CHECK (status IN ('pending','ready','stale','failed')),
  generated_at  timestamptz NOT NULL DEFAULT now(),
  stale_after   timestamptz,
  blob_uri      text,
  export_uri    text,
  summary       text
);
CREATE INDEX idx_admin_briefings_generated
  ON theeyebeta.admin_briefings(generated_at DESC);

CREATE TABLE theeyebeta.admin_intelligence_events (
  id          bigserial PRIMARY KEY,
  event_type  text NOT NULL,
  actor       text NOT NULL,
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_admin_intelligence_events_created
  ON theeyebeta.admin_intelligence_events(created_at DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_agent_control TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_agent_versions TO tb_app;
GRANT SELECT, UPDATE ON theeyebeta.admin_cost_state TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_cost_budgets TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_briefings TO tb_app;
GRANT SELECT, INSERT ON theeyebeta.admin_intelligence_events TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_cost_budgets_id_seq TO tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.admin_intelligence_events_id_seq TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_intelligence_events;
DROP TABLE IF EXISTS theeyebeta.admin_briefings;
DROP TABLE IF EXISTS theeyebeta.admin_cost_budgets;
DROP TABLE IF EXISTS theeyebeta.admin_cost_state;
DROP TABLE IF EXISTS theeyebeta.admin_agent_versions;
DROP TABLE IF EXISTS theeyebeta.admin_agent_control;

ALTER TABLE theeyebeta.proposals DROP CONSTRAINT IF EXISTS proposals_status_check;
ALTER TABLE theeyebeta.proposals ADD CONSTRAINT proposals_status_check
  CHECK (status IN ('pending','approved','rejected','superseded','applied'));
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
