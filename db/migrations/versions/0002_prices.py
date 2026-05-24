"""prices
Revision ID: 0002_prices
Revises: 0001_instruments
"""
from alembic import op

revision = "0002_prices"
down_revision = "0001_instruments"

SQL_UP = """
CREATE TABLE theeyebeta.prices_daily (
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  ts            timestamptz NOT NULL,
  open          numeric(18,6) NOT NULL,
  high          numeric(18,6) NOT NULL,
  low           numeric(18,6) NOT NULL,
  close         numeric(18,6) NOT NULL,
  adj_close     numeric(18,6),
  volume        bigint NOT NULL,
  vwap          numeric(18,6),
  source        text NOT NULL,
  ingested_at   timestamptz NOT NULL DEFAULT now()
);
SELECT create_hypertable('theeyebeta.prices_daily', 'ts', chunk_time_interval => INTERVAL '1 month');
CREATE UNIQUE INDEX idx_prices_daily_uniq ON theeyebeta.prices_daily (instrument_id, ts);
ALTER TABLE theeyebeta.prices_daily SET (timescaledb.compress, timescaledb.compress_segmentby='instrument_id');
SELECT add_compression_policy('theeyebeta.prices_daily', INTERVAL '90 days');

CREATE TABLE theeyebeta.prices_intraday (
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  ts            timestamptz NOT NULL,
  bar_seconds   int NOT NULL,
  open numeric(18,6), high numeric(18,6), low numeric(18,6), close numeric(18,6),
  volume bigint,
  source text NOT NULL
);
SELECT create_hypertable('theeyebeta.prices_intraday', 'ts', chunk_time_interval => INTERVAL '7 days');
CREATE UNIQUE INDEX idx_prices_intraday_uniq ON theeyebeta.prices_intraday(instrument_id, bar_seconds, ts);

CREATE TABLE theeyebeta.corporate_actions (
  id bigserial PRIMARY KEY,
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  ex_date date NOT NULL,
  action_type text NOT NULL CHECK (action_type IN ('split','dividend','merger','spinoff','rename')),
  ratio_num numeric(18,8),
  ratio_den numeric(18,8),
  cash_amount numeric(18,6),
  currency_iso char(3),
  metadata jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX idx_corp_actions_inst_date ON theeyebeta.corporate_actions(instrument_id, ex_date);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.prices_daily, theeyebeta.prices_intraday,
      theeyebeta.corporate_actions TO tb_app;
GRANT SELECT ON theeyebeta.prices_daily, theeyebeta.prices_intraday,
      theeyebeta.corporate_actions TO tb_rnd_readonly;
"""

SQL_DOWN = """
SELECT remove_compression_policy('theeyebeta.prices_daily', if_exists => true);
DROP TABLE IF EXISTS theeyebeta.corporate_actions;
DROP TABLE IF EXISTS theeyebeta.prices_intraday;
DROP TABLE IF EXISTS theeyebeta.prices_daily;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
