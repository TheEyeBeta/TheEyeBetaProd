-- Minimal US seed for integration pipeline tests.
INSERT INTO theeyebeta.exchanges (code, name, country_iso2, timezone, currency_iso)
VALUES ('XNAS', 'NASDAQ', 'US', 'America/New_York', 'USD')
ON CONFLICT (code) DO NOTHING;

INSERT INTO theeyebeta.instruments (symbol, exchange_id, asset_class, active)
SELECT 'AAPL', e.id, 'equity', true
FROM theeyebeta.exchanges e
WHERE e.code = 'XNAS'
ON CONFLICT (symbol, exchange_id) DO UPDATE SET active = EXCLUDED.active;
