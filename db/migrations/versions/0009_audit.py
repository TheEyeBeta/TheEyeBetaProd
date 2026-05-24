"""audit
Revision ID: 0009_audit
Revises: 0008_costs
"""
from alembic import op
revision = "0009_audit"
down_revision = "0008_costs"

SQL_UP = """
-- Drop the placeholder from 0005
DROP TABLE IF EXISTS theeyebeta._audit_summary_placeholder;

-- Partitioned parent table
CREATE TABLE theeyebeta.audit_log (
  id bigserial,
  ts timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id text NOT NULL,
  payload jsonb NOT NULL,
  prev_hash bytea,
  row_hash bytea NOT NULL,
  PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE INDEX idx_audit_entity ON theeyebeta.audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_actor_ts ON theeyebeta.audit_log(actor, ts DESC);

-- Function that creates monthly partitions ahead of time.
CREATE OR REPLACE FUNCTION theeyebeta.ensure_audit_partitions(months_ahead int)
RETURNS void AS $f$
DECLARE
  m int;
  start_ts timestamptz;
  end_ts timestamptz;
  pname text;
BEGIN
  FOR m IN 0..months_ahead LOOP
    start_ts := date_trunc('month', now()) + (m || ' months')::interval;
    end_ts   := start_ts + INTERVAL '1 month';
    pname    := 'audit_log_' || to_char(start_ts, 'YYYY_MM');
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS theeyebeta.%I PARTITION OF theeyebeta.audit_log
         FOR VALUES FROM (%L) TO (%L)',
      pname, start_ts, end_ts
    );
  END LOOP;
END;
$f$ LANGUAGE plpgsql;

-- Materialize the next 6 partitions now.
SELECT theeyebeta.ensure_audit_partitions(6);

-- Sanitized view for tb_rnd_readonly (no payload PII, no order details).
CREATE OR REPLACE VIEW theeyebeta.system_audit_summary AS
  SELECT id, ts, actor, action, entity_type,
         CASE WHEN entity_type IN ('order','position','account')
              THEN '[redacted]' ELSE entity_id END AS entity_id_safe,
         jsonb_build_object(
           'kind', payload->>'kind',
           'outcome', payload->>'outcome',
           'risk_decision', payload->>'risk_decision'
         ) AS payload_summary
  FROM theeyebeta.audit_log;

-- Grants: tb_app gets INSERT + SELECT only (NO UPDATE, NO DELETE).
GRANT SELECT, INSERT ON theeyebeta.audit_log TO tb_app;
REVOKE UPDATE, DELETE ON theeyebeta.audit_log FROM tb_app;
GRANT USAGE, SELECT ON SEQUENCE theeyebeta.audit_log_id_seq TO tb_app;

-- tb_rnd_readonly: NO access to raw audit_log; can read sanitized view only.
REVOKE ALL ON theeyebeta.audit_log FROM tb_rnd_readonly;
GRANT SELECT ON theeyebeta.system_audit_summary TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP VIEW IF EXISTS theeyebeta.system_audit_summary;
DROP FUNCTION IF EXISTS theeyebeta.ensure_audit_partitions(int);
DROP TABLE IF EXISTS theeyebeta.audit_log CASCADE;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
