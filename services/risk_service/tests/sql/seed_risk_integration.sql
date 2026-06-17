-- Risk-service integration seed: portfolio tuned to fail VaR check 4 only.
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '880e8400-e29b-41d4-a716-446655440003',
    'rs-integration-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
VALUES (
    'a660e840-e29b-41d4-a716-446655440099',
    '880e8400-e29b-41d4-a716-446655440003',
    'rs-var-integration',
    '{
      "max_position_pct": 0.60,
      "max_sector_pct": 1.0,
      "max_correlation_cluster_pct": 1.0,
      "max_var": 0.02,
      "max_drawdown_pct": 0.50,
      "max_hhi": 0.90
    }'::jsonb
)
ON CONFLICT (id) DO UPDATE SET mandate = EXCLUDED.mandate;

INSERT INTO theeyebeta.instruments (symbol, exchange_id, asset_class, active, metadata)
SELECT 'MSFT', e.id, 'equity', true, '{"sector": "technology", "cluster": "tech"}'::jsonb
  FROM theeyebeta.exchanges e
 WHERE e.code = 'XNAS'
ON CONFLICT (symbol, exchange_id) DO UPDATE
   SET metadata = EXCLUDED.metadata,
       active = EXCLUDED.active;

UPDATE theeyebeta.instruments
   SET metadata = '{"sector": "technology", "cluster": "tech"}'::jsonb
 WHERE symbol = 'AAPL';

INSERT INTO theeyebeta.positions (
    portfolio_id,
    instrument_id,
    qty,
    avg_entry_price,
    market_value,
    opened_at
)
SELECT
    'a660e840-e29b-41d4-a716-446655440099'::uuid,
    i.id,
    v.qty,
    v.avg_entry_price,
    v.market_value,
    now()
  FROM (VALUES
    ('AAPL', 3500.0, 100.0, 350000.0),
    ('MSFT', 3000.0, 150.0, 450000.0)
  ) AS v(symbol, qty, avg_entry_price, market_value)
  JOIN theeyebeta.instruments i ON i.symbol = v.symbol
ON CONFLICT (portfolio_id, instrument_id) DO UPDATE
   SET qty = EXCLUDED.qty,
       market_value = EXCLUDED.market_value,
       updated_at = now();

INSERT INTO theeyebeta.risk_metrics (
    portfolio_id,
    ts,
    var_95,
    cvar_95,
    max_drawdown,
    gross_exposure,
    net_exposure,
    beta_spy,
    concentration_hhi,
    raw
)
VALUES (
    'a660e840-e29b-41d4-a716-446655440099'::uuid,
    now() - interval '1 hour',
    0.12,
    0.14,
    0.05,
    800000.0,
    800000.0,
    1.0,
    0.64,
    '{
      "return_samples": [
        -0.20, -0.19, -0.18, -0.17, -0.16, -0.15, -0.14, -0.13, -0.12, -0.11,
        0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10
      ],
      "wealth_30d": [1000000, 995000, 990000, 985000, 980000],
      "cluster_exposures": {"tech": 0.80}
    }'::jsonb
);
