"""instruments
Revision ID: 0001_instruments
Revises: 0000_extensions
"""
from alembic import op

revision = "0001_instruments"
down_revision = "0000_extensions"
branch_labels = None
depends_on = None

SQL_UP = """
CREATE TABLE theeyebeta.exchanges (
  id            smallserial PRIMARY KEY,
  code          text NOT NULL UNIQUE,
  name          text NOT NULL,
  country_iso2  char(2) NOT NULL,
  timezone      text NOT NULL,
  currency_iso  char(3) NOT NULL
);

CREATE TABLE theeyebeta.instruments (
  id             bigserial PRIMARY KEY,
  symbol         text NOT NULL,
  exchange_id    smallint NOT NULL REFERENCES theeyebeta.exchanges(id),
  isin           text,
  cusip          text,
  figi           text UNIQUE,
  asset_class    text NOT NULL CHECK (asset_class IN ('equity','etf','adr','index','crypto')),
  sector         text,
  industry       text,
  active         boolean NOT NULL DEFAULT true,
  listed_at      date,
  delisted_at    date,
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (symbol, exchange_id)
);
CREATE INDEX idx_instruments_active ON theeyebeta.instruments(active) WHERE active;
CREATE INDEX idx_instruments_sector ON theeyebeta.instruments(sector);

CREATE TABLE theeyebeta.market_calendars (
  id           bigserial PRIMARY KEY,
  exchange_id  smallint NOT NULL REFERENCES theeyebeta.exchanges(id),
  trade_date   date NOT NULL,
  open_time    time NOT NULL,
  close_time   time NOT NULL,
  is_half_day  boolean NOT NULL DEFAULT false,
  UNIQUE (exchange_id, trade_date)
);

CREATE TABLE theeyebeta.holidays (
  exchange_id  smallint NOT NULL REFERENCES theeyebeta.exchanges(id),
  holiday_date date NOT NULL,
  name         text NOT NULL,
  PRIMARY KEY (exchange_id, holiday_date)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.exchanges, theeyebeta.instruments,
      theeyebeta.market_calendars, theeyebeta.holidays TO tb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.exchanges, theeyebeta.instruments,
      theeyebeta.market_calendars, theeyebeta.holidays TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.holidays;
DROP TABLE IF EXISTS theeyebeta.market_calendars;
DROP TABLE IF EXISTS theeyebeta.instruments;
DROP TABLE IF EXISTS theeyebeta.exchanges;
"""

def upgrade():
    op.execute(SQL_UP)

def downgrade():
    op.execute(SQL_DOWN)
