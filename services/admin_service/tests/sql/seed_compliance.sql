-- Compliance cockpit integration seed.
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '880e8400-e29b-41d4-a716-446655440004',
    'admin-compliance-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
VALUES (
    'b770e8400-e29b-41d4-a716-446655440088',
    '880e8400-e29b-41d4-a716-446655440004',
    'admin-compliance-cockpit',
    '{
      "compliance": {
        "no_hk_dual_class": false,
        "blocked_markets": [],
        "max_day_trades_5d": 3,
        "aml_small_trade_usd": 10000,
        "aml_small_trade_count": 3
      }
    }'::jsonb
)
ON CONFLICT (id) DO UPDATE SET mandate = EXCLUDED.mandate;

INSERT INTO theeyebeta.compliance_checks (
    portfolio_id,
    rule_id,
    outcome,
    detail,
    checked_at
)
VALUES
    (
        'b770e8400-e29b-41d4-a716-446655440088'::uuid,
        'restricted_list',
        'pass',
        'symbol not restricted',
        now() - interval '2 hours'
    ),
    (
        'b770e8400-e29b-41d4-a716-446655440088'::uuid,
        'pdt_rule',
        'warn',
        'approaching day trade limit',
        now() - interval '1 hour'
    ),
    (
        'b770e8400-e29b-41d4-a716-446655440088'::uuid,
        'wash_sale',
        'block',
        'wash sale window active',
        now() - interval '30 minutes'
    );
