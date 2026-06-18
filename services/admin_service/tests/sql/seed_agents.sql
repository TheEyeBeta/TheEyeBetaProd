-- Admin agents API integration seed.

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
        'agents/markets/technical-analyst.agent.md',
        true
    ),
    (
        'macro-lead',
        'markets',
        'Macro and cross-asset stance',
        'claude-sonnet-4-6',
        'gpt-5',
        'agents/markets/macro-lead.agent.md',
        true
    )
ON CONFLICT (id) DO UPDATE
   SET department = EXCLUDED.department,
       role = EXCLUDED.role,
       model_default = EXCLUDED.model_default,
       model_fallback = EXCLUDED.model_fallback,
       constitution_path = EXCLUDED.constitution_path,
       active = true,
       updated_at = now();

-- Recent runs for technical-analyst (4 succeeded + 1 failed in 7d).
INSERT INTO theeyebeta.agent_runs (
    id, agent_id, triggered_by, started_at, ended_at, status,
    total_input_tokens, total_output_tokens, total_cost_usd
)
VALUES
    (
        'aa000000-0000-0000-0000-000000000001',
        'technical-analyst',
        'orchestrator',
        now() - interval '6 days',
        now() - interval '6 days' + interval '5 seconds',
        'succeeded',
        1000, 200, 0.05
    ),
    (
        'aa000000-0000-0000-0000-000000000002',
        'technical-analyst',
        'orchestrator',
        now() - interval '4 days',
        now() - interval '4 days' + interval '4 seconds',
        'succeeded',
        1100, 220, 0.06
    ),
    (
        'aa000000-0000-0000-0000-000000000003',
        'technical-analyst',
        'orchestrator',
        now() - interval '2 days',
        now() - interval '2 days' + interval '6 seconds',
        'succeeded',
        1200, 210, 0.06
    ),
    (
        'aa000000-0000-0000-0000-000000000004',
        'technical-analyst',
        'admin-api:other',
        now() - interval '1 day',
        now() - interval '1 day' + interval '7 seconds',
        'failed',
        500, 0, 0.01
    ),
    (
        'aa000000-0000-0000-0000-000000000005',
        'technical-analyst',
        'orchestrator',
        now() - interval '12 hours',
        now() - interval '12 hours' + interval '5 seconds',
        'succeeded',
        1300, 240, 0.07
    )
ON CONFLICT (id) DO NOTHING;
