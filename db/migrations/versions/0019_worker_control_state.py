"""Worker / timer control state for admin-service

Revision ID: 0019_worker_control_state
Revises: 0018_admin_rbac
"""

from alembic import op

revision = "0019_worker_control_state"
down_revision = "0018_admin_rbac"

SQL_UP = """
CREATE TABLE IF NOT EXISTS public.audit_worker_runs (
    run_id              BIGSERIAL PRIMARY KEY,
    worker_name         VARCHAR(64) NOT NULL,
    worker_type         VARCHAR(32) NOT NULL DEFAULT 'system',
    trade_date          DATE NOT NULL DEFAULT CURRENT_DATE,
    run_type            VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    status              VARCHAR(16) NOT NULL DEFAULT 'STARTED',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at            TIMESTAMPTZ,
    duration_seconds    INTEGER,
    records_expected    INTEGER,
    records_written     INTEGER,
    records_failed      INTEGER DEFAULT 0,
    error_class         VARCHAR(128),
    error_message       TEXT,
    error_stack         TEXT,
    metadata            JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.worker_heartbeats (
    worker_id           VARCHAR(64) PRIMARY KEY,
    worker_type         VARCHAR(32) NOT NULL DEFAULT 'system',
    status              VARCHAR(32) NOT NULL DEFAULT 'stopped',
    last_heartbeat      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error          TEXT,
    metadata            JSONB
);

CREATE TABLE theeyebeta.admin_worker_control (
  name               text PRIMARY KEY,
  kind               text NOT NULL CHECK (kind IN ('worker', 'timer')),
  paused             boolean NOT NULL DEFAULT false,
  enabled            boolean NOT NULL DEFAULT true,
  schedule_override  text,
  config             jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  updated_by         text
);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_worker_control TO tb_app;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'audit_worker_runs'
  ) THEN
    GRANT SELECT ON public.audit_worker_runs TO tb_app;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'worker_heartbeats'
  ) THEN
    GRANT SELECT ON public.worker_heartbeats TO tb_app;
  END IF;
END $$;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_worker_control;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
