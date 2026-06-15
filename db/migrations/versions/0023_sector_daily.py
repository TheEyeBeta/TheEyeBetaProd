"""sector_daily

Revision ID: 0023_sector_daily
Revises: 0022_ind_technical_daily
"""

from alembic import op

revision = "0023_sector_daily"
down_revision = "0022_ind_technical_daily"

SQL_UP = """
CREATE TABLE IF NOT EXISTS theeyebeta.sector_daily (
  sector text NOT NULL,
  as_of_date date NOT NULL,
  n_instruments integer NOT NULL DEFAULT 0,
  avg_return_1d numeric(12, 6),
  avg_return_5d numeric(12, 6),
  avg_return_30d numeric(12, 6),
  median_rsi_14 numeric(8, 4),
  pct_above_sma_50 numeric(6, 4),
  pct_above_sma_200 numeric(6, 4),
  rel_strength_spx_30d numeric(12, 6),
  rotation_rank smallint,
  volume_ratio_20d numeric(12, 6),
  top_contributors jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sector, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_sector_daily_date
  ON theeyebeta.sector_daily (as_of_date DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.sector_daily TO tb_app;
GRANT SELECT ON theeyebeta.sector_daily TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.sector_daily;
"""


def upgrade() -> None:
    """Ensure sector_daily exists in the Alembic chain."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop sector_daily."""
    op.execute(SQL_DOWN)
