-- Admin guard API integration seed.

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

-- Parent runs referenced by violations.
INSERT INTO theeyebeta.agent_runs (
    id, agent_id, triggered_by, started_at, ended_at, status
)
VALUES
    (
        'bb000000-0000-0000-0000-000000000001',
        'technical-analyst',
        'orchestrator',
        now() - interval '3 hours',
        now() - interval '3 hours' + interval '5 seconds',
        'failed'
    ),
    (
        'bb000000-0000-0000-0000-000000000002',
        'macro-lead',
        'orchestrator',
        now() - interval '2 hours',
        now() - interval '2 hours' + interval '4 seconds',
        'failed'
    ),
    (
        'bb000000-0000-0000-0000-000000000003',
        'technical-analyst',
        'orchestrator',
        now() - interval '1 hour',
        now() - interval '1 hour' + interval '5 seconds',
        'failed'
    )
ON CONFLICT (id) DO NOTHING;

-- Three guard violations: pending TA-low, pending macro-high, already-resolved.
INSERT INTO theeyebeta.guard_violations (
    ts, run_id, agent_id, violation_type, severity, detail, resolution, resolved
)
VALUES
    (
        now() - interval '3 hours',
        'bb000000-0000-0000-0000-000000000001',
        'technical-analyst',
        'schema',
        'low',
        '{"field": "decision", "expected": "BUY|SELL|HOLD"}'::jsonb,
        'retry',
        false
    ),
    (
        now() - interval '2 hours',
        'bb000000-0000-0000-0000-000000000002',
        'macro-lead',
        'mandate_boundary',
        'high',
        '{"target": "compliance_rule", "denied": true}'::jsonb,
        'reject',
        false
    );

INSERT INTO theeyebeta.guard_violations (
    ts, run_id, agent_id, violation_type, severity, detail, resolution,
    resolved, resolved_by, resolved_at, resolution_note
)
VALUES
    (
        now() - interval '1 hour',
        'bb000000-0000-0000-0000-000000000003',
        'technical-analyst',
        'confidence_range',
        'medium',
        '{"value": 1.2}'::jsonb,
        'retry',
        true,
        'admin-api:legacy-operator',
        now() - interval '30 minutes',
        'manual override'
    );
