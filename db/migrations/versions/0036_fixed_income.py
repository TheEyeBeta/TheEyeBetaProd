"""fixed_income

Revision ID: 0036_fixed_income
Revises: 0035_openai_agent_models

Create derived fixed-income regime tables and seed ETF proxies.
"""

from alembic import op

revision = "0036_fixed_income"
down_revision = "0035_openai_agent_models"
branch_labels = None
depends_on = None

SQL_UP = """
CREATE TABLE IF NOT EXISTS theeyebeta.fixed_income_curve_metrics (
  date date NOT NULL,
  country text NOT NULL DEFAULT 'US',
  currency text NOT NULL DEFAULT 'USD',
  y_1mo numeric(10,4),
  y_3mo numeric(10,4),
  y_6mo numeric(10,4),
  y_1y numeric(10,4),
  y_2y numeric(10,4),
  y_5y numeric(10,4),
  y_10y numeric(10,4),
  y_20y numeric(10,4),
  y_30y numeric(10,4),
  spread_10y_2y numeric(10,4),
  spread_10y_3m numeric(10,4),
  spread_30y_5y numeric(10,4),
  real_yield_10y numeric(10,4),
  high_yield_spread numeric(10,4),
  ig_corp_spread numeric(10,4),
  y_2y_change_5d numeric(10,4),
  y_10y_change_5d numeric(10,4),
  y_30y_change_5d numeric(10,4),
  y_2y_change_20d numeric(10,4),
  y_10y_change_20d numeric(10,4),
  y_30y_change_20d numeric(10,4),
  y_10y_volatility_20d numeric(10,4),
  curve_regime text NOT NULL DEFAULT 'unknown',
  rate_regime text NOT NULL DEFAULT 'unknown',
  credit_regime text NOT NULL DEFAULT 'unknown',
  bond_environment_score integer CHECK (
    bond_environment_score IS NULL OR bond_environment_score BETWEEN 0 AND 100
  ),
  bond_environment_label text,
  source text NOT NULL DEFAULT 'fred',
  computed_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (date, country)
);

CREATE INDEX IF NOT EXISTS idx_fixed_income_curve_metrics_country_date
  ON theeyebeta.fixed_income_curve_metrics (country, date DESC);
CREATE INDEX IF NOT EXISTS idx_fixed_income_curve_metrics_label
  ON theeyebeta.fixed_income_curve_metrics (bond_environment_label);

CREATE TABLE IF NOT EXISTS theeyebeta.fixed_income_signals (
  id bigserial PRIMARY KEY,
  date date NOT NULL,
  country text NOT NULL DEFAULT 'US',
  signal_name text NOT NULL,
  signal_value numeric(12,4),
  signal_strength text NOT NULL,
  signal_direction text NOT NULL,
  interpretation text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (date, country, signal_name)
);

CREATE INDEX IF NOT EXISTS idx_fixed_income_signals_country_date
  ON theeyebeta.fixed_income_signals (country, date DESC);
CREATE INDEX IF NOT EXISTS idx_fixed_income_signals_name_date
  ON theeyebeta.fixed_income_signals (signal_name, date DESC);

INSERT INTO theeyebeta.exchanges (code, name, country_iso2, timezone, currency_iso)
VALUES ('ARCX', 'NYSE Arca', 'US', 'America/New_York', 'USD')
ON CONFLICT (code) DO NOTHING;

WITH proxy_seed(symbol, exchange_code, name, industry, proxy_type, issuer_type) AS (
  VALUES
    ('SHY', 'ARCX', 'iShares 1-3 Year Treasury Bond ETF', 'Short Treasury ETF', 'short_treasury', 'government'),
    ('IEF', 'ARCX', 'iShares 7-10 Year Treasury Bond ETF', 'Intermediate Treasury ETF', 'intermediate_treasury', 'government'),
    ('TLT', 'ARCX', 'iShares 20+ Year Treasury Bond ETF', 'Long Treasury ETF', 'long_treasury', 'government'),
    ('TIP', 'ARCX', 'iShares TIPS Bond ETF', 'TIPS ETF', 'inflation_linked', 'government'),
    ('BND', 'XNAS', 'Vanguard Total Bond Market ETF', 'Aggregate Bond ETF', 'aggregate_bond', 'aggregate'),
    ('AGG', 'ARCX', 'iShares Core U.S. Aggregate Bond ETF', 'Aggregate Bond ETF', 'aggregate_bond', 'aggregate')
),
resolved AS (
  SELECT
      s.symbol,
      e.id AS exchange_id,
      s.name,
      s.industry,
      s.proxy_type,
      s.issuer_type
    FROM proxy_seed s
    JOIN theeyebeta.exchanges e ON e.code = s.exchange_code
)
INSERT INTO theeyebeta.instruments
    (symbol, exchange_id, asset_class, sector, industry, active, metadata)
SELECT
    symbol,
    exchange_id,
    'etf',
    'Fixed Income',
    industry,
    true,
    jsonb_build_object(
      'name', name,
      'fixed_income_proxy', true,
      'fixed_income_proxy_type', proxy_type,
      'fixed_income_issuer_type', issuer_type,
      'source', '0036_fixed_income'
    )
  FROM resolved
ON CONFLICT (symbol, exchange_id) DO UPDATE SET
    asset_class = 'etf',
    sector = 'Fixed Income',
    industry = EXCLUDED.industry,
    active = true,
    metadata = theeyebeta.instruments.metadata || EXCLUDED.metadata,
    updated_at = now();

WITH proxy_classification(symbol, industry, proxy_type, issuer_type) AS (
  VALUES
    ('SHY', 'Short Treasury ETF', 'short_treasury', 'government'),
    ('IEF', 'Intermediate Treasury ETF', 'intermediate_treasury', 'government'),
    ('TLT', 'Long Treasury ETF', 'long_treasury', 'government'),
    ('TIP', 'TIPS ETF', 'inflation_linked', 'government'),
    ('BND', 'Aggregate Bond ETF', 'aggregate_bond', 'aggregate'),
    ('AGG', 'Aggregate Bond ETF', 'aggregate_bond', 'aggregate')
)
UPDATE theeyebeta.instruments i
   SET asset_class = 'etf',
       sector = 'Fixed Income',
       industry = c.industry,
       active = true,
       metadata = i.metadata || jsonb_build_object(
         'fixed_income_proxy', true,
         'fixed_income_proxy_type', c.proxy_type,
         'fixed_income_issuer_type', c.issuer_type,
         'source', '0036_fixed_income'
       ),
       updated_at = now()
  FROM proxy_classification c
 WHERE i.symbol = c.symbol;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  theeyebeta.fixed_income_curve_metrics,
  theeyebeta.fixed_income_signals
TO tb_app;
GRANT SELECT ON
  theeyebeta.fixed_income_curve_metrics,
  theeyebeta.fixed_income_signals
TO tb_rnd_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.fixed_income_signals;
DROP TABLE IF EXISTS theeyebeta.fixed_income_curve_metrics;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
