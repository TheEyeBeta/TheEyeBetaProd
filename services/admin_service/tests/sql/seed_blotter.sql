-- Blotter integration seed: live order, execution, position.
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '990e8400-e29b-41d4-a716-446655440011',
    'admin-blotter-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name)
VALUES (
    'bb0e8400-e29b-41d4-a716-446655440011',
    '990e8400-e29b-41d4-a716-446655440011',
    'admin-blotter-test'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.orders (
    id, client_order_id, portfolio_id, instrument_id, side, order_type, qty, status, filled_qty
)
SELECT
    'dd0e8400-e29b-41d4-a716-446655440001'::uuid,
    'blotter-submitted-001',
    'bb0e8400-e29b-41d4-a716-446655440011'::uuid,
    i.id,
    'buy',
    'market',
    2.0,
    'submitted',
    0
  FROM theeyebeta.instruments i WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE SET status = 'submitted', updated_at = now();

INSERT INTO theeyebeta.positions (
    portfolio_id, instrument_id, qty, avg_entry_price, market_value, opened_at, updated_at
)
SELECT
    'bb0e8400-e29b-41d4-a716-446655440011'::uuid,
    i.id,
    10.0,
    150.0,
    1500.0,
    now() - interval '1 day',
    now() - interval '2 hours'
  FROM theeyebeta.instruments i WHERE i.symbol = 'AAPL'
ON CONFLICT (portfolio_id, instrument_id) DO UPDATE
   SET qty = EXCLUDED.qty, updated_at = EXCLUDED.updated_at;

INSERT INTO theeyebeta.executions (order_id, ts, qty, price, commission, raw)
VALUES (
    'dd0e8400-e29b-41d4-a716-446655440001'::uuid,
    now() - interval '1 hour',
    1.0,
    151.0,
    0.0,
    '{"source":"seed"}'::jsonb
);
