"""extensions sanity check
Revision ID: 0000_extensions
Revises:
Create Date: 2026-05-21 00:00:00
"""
from alembic import op

revision = "0000_extensions"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Extensions were created in pgAdmin4 preflight; this verifies they exist.
    op.execute("DO $$ BEGIN "
               "IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='timescaledb') THEN "
               "  RAISE EXCEPTION 'timescaledb extension missing — run preflight in pgAdmin4'; END IF; "
               "IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='vector') THEN "
               "  RAISE EXCEPTION 'pgvector extension missing — run preflight in pgAdmin4'; END IF; "
               "IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='pgcrypto') THEN "
               "  RAISE EXCEPTION 'pgcrypto extension missing'; END IF; "
               "IF NOT EXISTS (SELECT FROM pg_namespace WHERE nspname='theeyebeta') THEN "
               "  RAISE EXCEPTION 'theeyebeta schema missing — run preflight in pgAdmin4'; END IF; "
               "END $$;")

def downgrade():
    pass  # extensions and schema are owned by preflight, not Alembic
