"""rnd_readonly_views — system.agent_constitutions + rnd write grants
Revision ID: 0015_rnd_readonly_views
Revises: 0014_audit_checkpoints
"""
from alembic import op

revision = "0015_rnd_readonly_views"
down_revision = "0014_audit_checkpoints"

SQL_UP = """
CREATE SCHEMA IF NOT EXISTS system;

CREATE OR REPLACE VIEW system.agent_constitutions AS
  SELECT
    a.id AS agent_id,
    a.department,
    a.role,
    a.constitution_path,
    a.model_default,
    a.model_fallback,
    a.active,
    a.updated_at
  FROM theeyebeta.agents a
  WHERE a.active = true;

COMMENT ON VIEW system.agent_constitutions IS
  'Active agent registry for rnd-agent; constitution bodies are read from repo paths.';

GRANT USAGE ON SCHEMA system TO tb_rnd_readonly;
GRANT SELECT ON system.agent_constitutions TO tb_rnd_readonly;

-- rnd-agent service lifecycle (P-RND-02)
GRANT INSERT, UPDATE ON theeyebeta.agent_runs TO tb_rnd_readonly;
GRANT INSERT ON theeyebeta.model_runs TO tb_rnd_readonly;

INSERT INTO theeyebeta.agents
    (id, department, role, model_default, model_fallback, constitution_path, active)
VALUES
    (
        'rnd-agent',
        'research',
        'R&D proposal synthesis',
        'gpt-5',
        'claude-sonnet-4-6',
        'agents/rnd/rnd_agent.agent.md',
        true
    )
ON CONFLICT (id) DO UPDATE SET
    model_default = EXCLUDED.model_default,
    model_fallback = EXCLUDED.model_fallback,
    constitution_path = EXCLUDED.constitution_path,
    active = true,
    updated_at = now();
"""

SQL_DOWN = """
DELETE FROM theeyebeta.agents WHERE id = 'rnd-agent';
REVOKE INSERT ON theeyebeta.model_runs FROM tb_rnd_readonly;
REVOKE INSERT, UPDATE ON theeyebeta.agent_runs FROM tb_rnd_readonly;
REVOKE SELECT ON system.agent_constitutions FROM tb_rnd_readonly;
REVOKE USAGE ON SCHEMA system FROM tb_rnd_readonly;
DROP VIEW IF EXISTS system.agent_constitutions;
"""


def upgrade() -> None:
    """Expose agent_constitutions view and rnd-service write grants."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Revert rnd readonly extensions."""
    op.execute(SQL_DOWN)
