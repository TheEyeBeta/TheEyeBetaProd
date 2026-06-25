-- Risk cockpit integration seed (portfolio + metrics with VaR breach).
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '880e8400-e29b-41d4-a716-446655440003',
    'admin-risk-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
VALUES (
    'a660e8400-e29b-41d4-a716-446655440099',
    '880e8400-e29b-41d4-a716-446655440003',
    'admin-risk-cockpit',
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
    'a660e8400-e29b-41d4-a716-446655440099'::uuid,
    now() - interval '1 hour',
    0.12,
    0.14,
    0.05,
    800000.0,
    800000.0,
    1.0,
    0.64,
    '{
      "cluster_exposures": {"tech": 0.80},
      "validation": {
        "outcome": "BLOCK",
        "failed_checks": ["portfolio_var_95"]
      }
    }'::jsonb
);
