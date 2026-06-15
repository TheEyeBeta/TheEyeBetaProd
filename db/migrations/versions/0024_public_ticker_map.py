"""public_ticker_map

Revision ID: 0024_public_ticker_map
Revises: 0023_sector_daily
"""

from alembic import op

revision = "0024_public_ticker_map"
down_revision = "0023_sector_daily"

SQL_UP = """
CREATE TABLE IF NOT EXISTS theeyebeta.public_ticker_map (
  instrument_id bigint PRIMARY KEY REFERENCES theeyebeta.instruments(id),
  public_ticker_id bigint NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_public_ticker_map_public_id
  ON theeyebeta.public_ticker_map (public_ticker_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.public_ticker_map TO tb_app;
GRANT SELECT ON theeyebeta.public_ticker_map TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.public_ticker_map;
"""


def upgrade() -> None:
    """Formalize instrument bridge table in Alembic."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop bridge table."""
    op.execute(SQL_DOWN)
