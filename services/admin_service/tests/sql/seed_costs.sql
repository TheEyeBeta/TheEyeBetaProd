-- Admin costs API integration seed.
--
-- Two agents, three agent_runs, four model_runs spanning the current month
-- and the previous one, plus a few api_costs rows for the past few days.

INSERT INTO theeyebeta.agents (
    id, department, role, model_default, model_fallback, constitution_path, active
)
VALUES
    (
        'technical-analyst',
        'markets',
        'Technical analysis',
        'gpt-4o-mini',
        NULL,
        'agents/technical-analyst.md',
        true
    ),
    (
        'macro-lead',
        'markets',
        'Macro and cross-asset stance',
        'claude-sonnet-4-6',
        'gpt-5',
        'agents/macro-lead.md',
        true
    )
ON CONFLICT (id) DO UPDATE
   SET active = true, updated_at = now();

-- Agent runs: TA-current, macro-current, TA-previous-month.
INSERT INTO theeyebeta.agent_runs (
    id, agent_id, triggered_by, started_at, ended_at, status
)
VALUES
    (
        'dd000000-0000-0000-0000-000000000001',
        'technical-analyst',
        'orchestrator',
        date_trunc('month', now()) + interval '5 days',
        date_trunc('month', now()) + interval '5 days' + interval '5 seconds',
        'succeeded'
    ),
    (
        'dd000000-0000-0000-0000-000000000002',
        'macro-lead',
        'orchestrator',
        date_trunc('month', now()) + interval '6 days',
        date_trunc('month', now()) + interval '6 days' + interval '4 seconds',
        'succeeded'
    ),
    (
        'dd000000-0000-0000-0000-000000000003',
        'technical-analyst',
        'orchestrator',
        date_trunc('month', now()) - interval '20 days',
        date_trunc('month', now()) - interval '20 days' + interval '5 seconds',
        'succeeded'
    )
ON CONFLICT (id) DO NOTHING;

-- model_runs: 2 for TA-current ($0.10 + $0.05), 1 for macro-current ($0.20),
-- 1 for TA-previous ($0.50, should NOT show in current-month rollup).
-- Recent dates so they fall inside the default 30-day daily window.
INSERT INTO theeyebeta.model_runs (
    id, run_id, provider, model, input_tokens, output_tokens,
    cost_usd, status, kind, created_at
)
VALUES
    (
        'ee000000-0000-0000-0000-000000000001',
        'dd000000-0000-0000-0000-000000000001',
        'openai',
        'gpt-4o-mini',
        1000, 200, 0.10, 'success', 'completion',
        now() - interval '2 days'
    ),
    (
        'ee000000-0000-0000-0000-000000000002',
        'dd000000-0000-0000-0000-000000000001',
        'openai',
        'gpt-4o-mini',
        500, 100, 0.05, 'success', 'completion',
        now() - interval '1 day'
    ),
    (
        'ee000000-0000-0000-0000-000000000003',
        'dd000000-0000-0000-0000-000000000002',
        'anthropic',
        'claude-sonnet-4-6',
        2000, 400, 0.20, 'success', 'completion',
        now() - interval '1 day'
    ),
    (
        'ee000000-0000-0000-0000-000000000004',
        'dd000000-0000-0000-0000-000000000003',
        'openai',
        'gpt-4o-mini',
        4000, 800, 0.50, 'success', 'completion',
        date_trunc('month', now()) - interval '20 days'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.api_costs (ts, vendor, category, cost_usd, detail)
VALUES
    ((now() - interval '2 days')::date, 'polygon', 'market_data', 1.5000, '{}'::jsonb),
    ((now() - interval '1 day')::date,  'polygon', 'market_data', 1.7500, '{}'::jsonb)
ON CONFLICT (ts, vendor, category) DO NOTHING;
