"""openai_agent_models

Revision ID: 0035_openai_agent_models
Revises: 0034_audit_ckpt_select

Replace legacy Claude LiteLLM aliases with OpenAI model names in theeyebeta.agents.
"""

from alembic import op

revision = "0035_openai_agent_models"
down_revision = "0034_audit_ckpt_select"

SQL_UP = """
UPDATE theeyebeta.agents
   SET model_default = CASE model_default
         WHEN 'claude-sonnet-4-6' THEN 'gpt-4o-mini'
         WHEN 'claude-haiku-4-5' THEN 'gpt-4o-mini'
         ELSE model_default
       END,
       model_fallback = CASE model_fallback
         WHEN 'claude-sonnet-4-6' THEN 'gpt-4o-mini'
         WHEN 'claude-haiku-4-5' THEN 'gpt-4o-mini'
         ELSE model_fallback
       END,
       updated_at = now()
 WHERE model_default IN ('claude-sonnet-4-6', 'claude-haiku-4-5')
    OR model_fallback IN ('claude-sonnet-4-6', 'claude-haiku-4-5');
"""

SQL_DOWN = """
UPDATE theeyebeta.agents
   SET model_default = CASE model_default
         WHEN 'gpt-4o-mini' THEN 'claude-sonnet-4-6'
         ELSE model_default
       END,
       model_fallback = CASE model_fallback
         WHEN 'gpt-4o-mini' THEN 'claude-sonnet-4-6'
         ELSE model_fallback
       END,
       updated_at = now()
 WHERE id IN (
     SELECT id FROM theeyebeta.agents
      WHERE model_default = 'gpt-4o-mini' OR model_fallback = 'gpt-4o-mini'
 );
"""


def upgrade() -> None:
    """Map Claude alias names to OpenAI equivalents."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Restore Claude alias names (lossy for haiku → mini mappings)."""
    op.execute(SQL_DOWN)
