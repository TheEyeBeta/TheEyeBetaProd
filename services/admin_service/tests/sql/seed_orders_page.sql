-- Orders page integration seed — pending orders with rationale metadata so
-- the template can exercise truncation + expand and the modal reject flow.
-- Idempotent and isolated from seed_orders.sql (uses a distinct UUID block).

INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '990e8400-e29b-41d4-a716-446655440090',
    'admin-orders-page-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name)
VALUES (
    'bb0e8400-e29b-41d4-a716-446655440090',
    '990e8400-e29b-41d4-a716-446655440090',
    'admin-orders-page-test'
)
ON CONFLICT (id) DO NOTHING;

-- Pending order with a LONG rationale → truncated snippet + expand button.
INSERT INTO theeyebeta.orders (
    id, client_order_id, portfolio_id, instrument_id,
    side, order_type, qty, limit_price, status, metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440091'::uuid,
    'orders-page-long-001',
    'bb0e8400-e29b-41d4-a716-446655440090'::uuid,
    i.id,
    'buy',
    'limit',
    12.0,
    155.50,
    'pending_approval',
    jsonb_build_object(
        'rationale',
        'Persistent up-trend over the last 20 sessions, RSI(14) cooling from 78 to 62, '
        || 'volume confirms with three-bar bullish reclaim above 50d MA. Risk: macro '
        || 'CPI print on Thursday introduces tail risk above 1.5 sigma so size is '
        || 'capped at 0.75% NAV. Stop at $145, take-profit ladder at $168 / $174.'
    )
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = EXCLUDED.metadata,
       updated_at = now();

-- Pending order with a SHORT rationale → no expand needed.
INSERT INTO theeyebeta.orders (
    id, client_order_id, portfolio_id, instrument_id,
    side, order_type, qty, limit_price, status, metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440092'::uuid,
    'orders-page-short-002',
    'bb0e8400-e29b-41d4-a716-446655440090'::uuid,
    i.id,
    'sell',
    'limit',
    4.5,
    192.10,
    'pending_approval',
    jsonb_build_object('rationale', 'Hit profit target. Exit half.')
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = EXCLUDED.metadata,
       updated_at = now();

-- Pending market-order with NO rationale at all → "no rationale recorded" copy.
INSERT INTO theeyebeta.orders (
    id, client_order_id, portfolio_id, instrument_id,
    side, order_type, qty, limit_price, status, metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440093'::uuid,
    'orders-page-norat-003',
    'bb0e8400-e29b-41d4-a716-446655440090'::uuid,
    i.id,
    'buy',
    'market',
    8.0,
    NULL,
    'pending_approval',
    '{}'::jsonb
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = '{}'::jsonb,
       updated_at = now();
