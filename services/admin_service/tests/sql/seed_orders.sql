-- Admin orders API integration seed (pending + approved reference rows).

INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '990e8400-e29b-41d4-a716-446655440010',
    'admin-orders-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name)
VALUES (
    'bb0e8400-e29b-41d4-a716-446655440010',
    '990e8400-e29b-41d4-a716-446655440010',
    'admin-orders-test'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.orders (
    id,
    client_order_id,
    portfolio_id,
    instrument_id,
    side,
    order_type,
    qty,
    limit_price,
    status,
    metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440001'::uuid,
    'admin-pending-001',
    'bb0e8400-e29b-41d4-a716-446655440010'::uuid,
    i.id,
    'buy',
    'limit',
    10.0,
    150.0,
    'pending_approval',
    '{}'::jsonb
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = '{}'::jsonb,
       updated_at = now();

INSERT INTO theeyebeta.orders (
    id,
    client_order_id,
    portfolio_id,
    instrument_id,
    side,
    order_type,
    qty,
    status,
    metadata,
    approved_by,
    approved_at
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440002'::uuid,
    'admin-approved-001',
    'bb0e8400-e29b-41d4-a716-446655440010'::uuid,
    i.id,
    'sell',
    'market',
    5.0,
    'approved',
    '{}'::jsonb,
    'seed',
    now() - interval '1 day'
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.orders (
    id,
    client_order_id,
    portfolio_id,
    instrument_id,
    side,
    order_type,
    qty,
    limit_price,
    status,
    metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440003'::uuid,
    'admin-pending-002',
    'bb0e8400-e29b-41d4-a716-446655440010'::uuid,
    i.id,
    'buy',
    'limit',
    25.0,
    200.0,
    'pending_approval',
    '{}'::jsonb
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = '{}'::jsonb,
       updated_at = now();
