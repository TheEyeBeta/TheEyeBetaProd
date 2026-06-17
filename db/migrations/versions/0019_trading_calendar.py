"""trading_calendar

Revision ID: 0019_trading_calendar
Revises: 0018_market_cap_universe
"""

from alembic import op

revision = "0019_trading_calendar"
down_revision = "0018_market_cap_universe"

SQL_UP = """
CREATE TABLE theeyebeta.trading_calendar (
  calendar_date date PRIMARY KEY,
  is_trading_day boolean NOT NULL DEFAULT true,
  market_name text NOT NULL DEFAULT 'US',
  holiday_name text,
  notes text
);

CREATE INDEX idx_trading_calendar_trading_day
  ON theeyebeta.trading_calendar (is_trading_day, calendar_date);

DO $$
BEGIN
  IF to_regclass('public.trading_calendar') IS NOT NULL THEN
    INSERT INTO theeyebeta.trading_calendar (
      calendar_date, is_trading_day, market_name, holiday_name, notes
    )
    SELECT calendar_date, is_trading_day,
           COALESCE(market_name, 'US'), holiday_name, notes
      FROM public.trading_calendar
    ON CONFLICT (calendar_date) DO NOTHING;
  END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.trading_calendar TO tb_app;
GRANT SELECT ON theeyebeta.trading_calendar TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.trading_calendar;
"""


def upgrade() -> None:
    """Create canonical trading calendar and seed from legacy public table."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop canonical trading calendar."""
    op.execute(SQL_DOWN)
