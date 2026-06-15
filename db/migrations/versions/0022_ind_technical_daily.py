"""ind_technical_daily

Revision ID: 0022_ind_technical_daily
Revises: 0021_pipeline_alerts
"""

from alembic import op

revision = "0022_ind_technical_daily"
down_revision = "0021_pipeline_alerts"

SQL_UP = """
CREATE TABLE theeyebeta.ind_technical_daily (
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  date date NOT NULL,
  ticker_id bigint NOT NULL,
  sma_10 numeric(20, 6),
  sma_50 numeric(20, 6),
  sma_200 numeric(20, 6),
  ema_10 numeric(20, 6),
  ema_50 numeric(20, 6),
  ema_200 numeric(20, 6),
  rsi_14 numeric(12, 4),
  macd numeric(20, 6),
  macd_signal numeric(20, 6),
  macd_hist numeric(20, 6),
  roc_10 numeric(12, 4),
  roc_20 numeric(12, 4),
  golden_cross_sma boolean,
  death_cross_sma boolean,
  as_of_date date,
  computed_at timestamptz,
  price_field text,
  compute_version text,
  ema_12 numeric(20, 6),
  ema_26 numeric(20, 6),
  momentum_rank_12_1 numeric(12, 4),
  PRIMARY KEY (instrument_id, date)
);

CREATE INDEX idx_ind_technical_daily_date
  ON theeyebeta.ind_technical_daily (date DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.ind_technical_daily TO tb_app;
GRANT SELECT ON theeyebeta.ind_technical_daily TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.ind_technical_daily;
"""


def upgrade() -> None:
    """Create canonical daily technical indicator table."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop canonical indicator table."""
    op.execute(SQL_DOWN)
