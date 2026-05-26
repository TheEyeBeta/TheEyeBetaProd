-- Admin proposals API integration seed.

INSERT INTO theeyebeta.strategies (id, name, description, config, active)
VALUES
    (
        'momentum-v1',
        'Momentum v1',
        'Test strategy for proposal validation backtests',
        '{}'::jsonb,
        true
    )
ON CONFLICT (id) DO UPDATE
   SET name = EXCLUDED.name,
       active = true;

INSERT INTO theeyebeta.proposals (
    id, proposed_by, run_id, category, target,
    current_value, proposed_value, rationale, evidence,
    estimated_impact, status
)
VALUES
    (
        'ff111111-1111-1111-1111-111111111111',
        'rnd-agent',
        NULL,
        'strategy_param',
        'momentum-v1',
        '{"lookback": 20}'::jsonb,
        '{"lookback": 30}'::jsonb,
        'Lengthening the lookback window reduces whipsaws on choppy days.',
        '{"backtest": "results/2024-q4.json", "n_signals_compared": 1200}'::jsonb,
        '{"sharpe_delta": 0.12}'::jsonb,
        'pending'
    ),
    (
        'ff222222-2222-2222-2222-222222222222',
        'rnd-agent',
        NULL,
        'agent_constitution',
        'macro-lead',
        '{"max_turns": 4}'::jsonb,
        '{"max_turns": 6}'::jsonb,
        'Allow more rebuttal rounds for macro debate quality.',
        '{"agent_decisions": 84, "ratio_with_rebuttals": 0.61}'::jsonb,
        NULL,
        'pending'
    ),
    (
        'ff333333-3333-3333-3333-333333333333',
        'rnd-agent',
        NULL,
        'risk_rule',
        'max_position_size',
        '{"limit": 0.05}'::jsonb,
        '{"limit": 0.04}'::jsonb,
        'Reduce single-name concentration after Q1 drawdown analysis.',
        '{"observations": 256}'::jsonb,
        NULL,
        'rejected'
    )
ON CONFLICT (id) DO NOTHING;
