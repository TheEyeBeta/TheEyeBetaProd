"""pipeline_alerts

Revision ID: 0021_pipeline_alerts
Revises: 0020_worker_ops
"""

from alembic import op

revision = "0021_pipeline_alerts"
down_revision = "0020_worker_ops"

SQL_UP = """
CREATE TABLE theeyebeta.audit_data_gaps (
  gap_id bigserial PRIMARY KEY,
  dataset_type varchar(32) NOT NULL,
  instrument_id bigint REFERENCES theeyebeta.instruments(id),
  ticker_id bigint,
  trade_date date NOT NULL,
  expected_start timestamptz NOT NULL,
  expected_end timestamptz NOT NULL,
  expected_count integer,
  actual_count integer DEFAULT 0,
  gap_start timestamptz,
  gap_end timestamptz,
  severity varchar(16) NOT NULL DEFAULT 'WARN'
    CHECK (severity IN ('INFO', 'WARN', 'CRITICAL')),
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(),
  metadata jsonb,
  remediation_state varchar(16) DEFAULT 'OPEN'
    CHECK (remediation_state IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'IGNORED')),
  remediation_notes text,
  acknowledged_by varchar(128),
  acknowledged_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_data_gaps_dataset_date
  ON theeyebeta.audit_data_gaps (dataset_type, trade_date DESC);
CREATE INDEX idx_audit_data_gaps_instrument_date
  ON theeyebeta.audit_data_gaps (instrument_id, trade_date DESC)
  WHERE instrument_id IS NOT NULL;
CREATE INDEX idx_audit_data_gaps_open
  ON theeyebeta.audit_data_gaps (trade_date DESC, severity)
  WHERE remediation_state = 'OPEN';

CREATE TABLE theeyebeta.audit_alerts (
  alert_id bigserial PRIMARY KEY,
  alert_type varchar(32) NOT NULL,
  severity varchar(16) NOT NULL DEFAULT 'WARN'
    CHECK (severity IN ('INFO', 'WARN', 'CRITICAL', 'ESCALATE')),
  trade_date date,
  worker_name varchar(64),
  gap_id bigint REFERENCES theeyebeta.audit_data_gaps(gap_id) ON DELETE SET NULL,
  run_id bigint REFERENCES theeyebeta.worker_runs(run_id) ON DELETE SET NULL,
  title varchar(256) NOT NULL,
  message text NOT NULL,
  routing_channels text[] DEFAULT ARRAY['slack']::text[],
  acknowledged_by varchar(128),
  acknowledged_at timestamptz,
  escalated_at timestamptz,
  resolved_at timestamptz,
  resolution_notes text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_alerts_severity_created
  ON theeyebeta.audit_alerts (severity, created_at DESC);
CREATE INDEX idx_audit_alerts_unacknowledged
  ON theeyebeta.audit_alerts (severity, created_at DESC)
  WHERE acknowledged_at IS NULL AND resolved_at IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON theeyebeta.audit_data_gaps, theeyebeta.audit_alerts TO tb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.audit_data_gaps, theeyebeta.audit_alerts TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.audit_alerts;
DROP TABLE IF EXISTS theeyebeta.audit_data_gaps;
"""


def upgrade() -> None:
    """Create pipeline gap and alert tables in theeyebeta schema."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop pipeline alert tables."""
    op.execute(SQL_DOWN)
