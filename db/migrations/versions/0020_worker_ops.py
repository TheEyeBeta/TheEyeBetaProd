"""worker_ops

Revision ID: 0020_worker_ops
Revises: 0019_trading_calendar
"""

from alembic import op

revision = "0020_worker_ops"
down_revision = "0019_trading_calendar"

SQL_UP = """
CREATE TABLE theeyebeta.worker_runs (
  run_id bigserial PRIMARY KEY,
  worker_name varchar(64) NOT NULL,
  worker_type varchar(32) NOT NULL,
  trade_date date NOT NULL,
  run_type varchar(32) NOT NULL
    CHECK (run_type IN ('scheduled', 'manual', 'recovery')),
  status varchar(16) NOT NULL
    CHECK (status IN ('STARTED', 'HEARTBEAT', 'COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED')),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  duration_seconds integer,
  records_expected integer,
  records_written integer,
  records_failed integer DEFAULT 0,
  error_class varchar(128),
  error_message text,
  error_stack text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_worker_runs_worker_date
  ON theeyebeta.worker_runs (worker_name, trade_date DESC);
CREATE INDEX idx_worker_runs_status_date
  ON theeyebeta.worker_runs (status, trade_date DESC);
CREATE UNIQUE INDEX idx_worker_runs_scheduled_unique
  ON theeyebeta.worker_runs (worker_name, trade_date)
  WHERE run_type = 'scheduled';

CREATE TABLE theeyebeta.worker_heartbeats (
  worker_id varchar(64) PRIMARY KEY,
  worker_type varchar(32) NOT NULL,
  status varchar(16) NOT NULL
    CHECK (status IN ('running', 'stopped', 'failed', 'restarting')),
  last_heartbeat timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  restart_count integer DEFAULT 0,
  last_error text,
  metadata jsonb
);

CREATE INDEX idx_worker_heartbeats_type
  ON theeyebeta.worker_heartbeats (worker_type);

CREATE TABLE theeyebeta.trask_components (
  id serial PRIMARY KEY,
  component_type varchar(32) NOT NULL,
  component_id varchar(64) NOT NULL UNIQUE,
  display_name varchar(128) NOT NULL,
  state varchar(32) NOT NULL DEFAULT 'STOPPED',
  last_heartbeat timestamptz,
  last_state_change timestamptz NOT NULL DEFAULT now(),
  error_count integer NOT NULL DEFAULT 0,
  restart_count integer NOT NULL DEFAULT 0,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT trask_components_valid_state CHECK (
    state IN ('STOPPED', 'STARTING', 'RUNNING', 'DEGRADED', 'STOPPING', 'FAILED')
  )
);

CREATE INDEX idx_trask_components_type ON theeyebeta.trask_components (component_type);
CREATE INDEX idx_trask_components_state ON theeyebeta.trask_components (state);

CREATE TABLE theeyebeta.trask_circuit_breakers (
  id serial PRIMARY KEY,
  component_id varchar(64) NOT NULL UNIQUE,
  state varchar(16) NOT NULL DEFAULT 'closed',
  failure_count integer NOT NULL DEFAULT 0,
  success_count integer NOT NULL DEFAULT 0,
  last_failure_at timestamptz,
  last_success_at timestamptz,
  opened_at timestamptz,
  config jsonb NOT NULL DEFAULT
    '{"failure_threshold": 3, "recovery_timeout_seconds": 300, "success_threshold": 2}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT trask_circuit_valid_state CHECK (state IN ('closed', 'open', 'half_open'))
);

INSERT INTO theeyebeta.trask_components (component_type, component_id, display_name, state)
VALUES
  ('worker', 'MacroIngestionWorker', 'Macro Ingestion Worker', 'STOPPED'),
  ('sentinel', 'MacroIngestionWorker_sentinel', 'Macro Ingestion Sentinel', 'STOPPED'),
  ('worker', 'MacroRegimeWorker', 'Macro Regime Worker', 'STOPPED'),
  ('sentinel', 'MacroRegimeWorker_sentinel', 'Macro Regime Sentinel', 'STOPPED'),
  ('worker', 'MassiveDailyIngestionWorker', 'Massive Daily Ingestion', 'STOPPED'),
  ('sentinel', 'MassiveDailyIngestionWorker_sentinel', 'Massive Ingest Sentinel', 'STOPPED'),
  ('worker', 'IntradayIngestionWorker', 'Intraday Ingestion', 'STOPPED'),
  ('sentinel', 'IntradayIngestionWorker_sentinel', 'Intraday Ingest Sentinel', 'STOPPED'),
  ('worker', 'TheeyebetaIndicatorWorker', 'Theeyebeta Indicator Worker', 'STOPPED'),
  ('sentinel', 'TheeyebetaIndicatorWorker_sentinel', 'Indicator Sentinel', 'STOPPED'),
  ('worker', 'IndicatorComputeWorker', 'Indicator Compute Worker', 'STOPPED'),
  ('sentinel', 'IndicatorComputeWorker_sentinel', 'Indicator Compute Sentinel', 'STOPPED'),
  ('worker', 'SectorAggregationWorker', 'Sector Aggregation', 'STOPPED'),
  ('sentinel', 'SectorAggregationWorker_sentinel', 'Sector Aggregation Sentinel', 'STOPPED'),
  ('worker', 'GapSentinelWorker', 'Gap Sentinel Worker', 'STOPPED'),
  ('sentinel', 'GapSentinelWorker_sentinel', 'Gap Sentinel Sentinel', 'STOPPED'),
  ('worker', 'daily_pipeline', 'Daily Pipeline', 'STOPPED'),
  ('sentinel', 'daily_pipeline_sentinel', 'Daily Pipeline Sentinel', 'STOPPED'),
  ('worker', 'MarketCapFetchWorker', 'Market Cap Fetch', 'STOPPED'),
  ('sentinel', 'MarketCapFetchWorker_sentinel', 'Market Cap Fetch Sentinel', 'STOPPED'),
  ('worker', 'MarketCapThresholdWorker', 'Market Cap Threshold', 'STOPPED'),
  ('sentinel', 'MarketCapThresholdWorker_sentinel', 'Market Cap Threshold Sentinel', 'STOPPED'),
  ('worker', 'CanonicalPriceMirror', 'Canonical Price Mirror', 'STOPPED'),
  ('sentinel', 'CanonicalPriceMirror_sentinel', 'Canonical Price Mirror Sentinel', 'STOPPED'),
  ('worker', 'SupabaseSyncV2', 'Supabase Sync v2', 'STOPPED'),
  ('sentinel', 'SupabaseSyncV2_sentinel', 'Supabase Sync v2 Sentinel', 'STOPPED')
ON CONFLICT (component_id) DO NOTHING;

INSERT INTO theeyebeta.trask_circuit_breakers (component_id)
SELECT component_id
  FROM theeyebeta.trask_components
 WHERE component_id LIKE '%_sentinel'
ON CONFLICT (component_id) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON theeyebeta.worker_runs, theeyebeta.worker_heartbeats,
     theeyebeta.trask_components, theeyebeta.trask_circuit_breakers TO tb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.worker_runs, theeyebeta.worker_heartbeats,
      theeyebeta.trask_components, theeyebeta.trask_circuit_breakers TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.trask_circuit_breakers;
DROP TABLE IF EXISTS theeyebeta.trask_components;
DROP TABLE IF EXISTS theeyebeta.worker_heartbeats;
DROP TABLE IF EXISTS theeyebeta.worker_runs;
"""


def upgrade() -> None:
    """Create canonical worker ops and Trask tables."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop canonical worker ops tables."""
    op.execute(SQL_DOWN)
