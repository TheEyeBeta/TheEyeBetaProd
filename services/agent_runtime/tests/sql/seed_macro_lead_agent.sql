-- Agent-runtime integration: macro-lead agent row.
INSERT INTO theeyebeta.agents
    (id, department, role, model_default, model_fallback, constitution_path, active)
VALUES
    (
        'macro-lead',
        'markets',
        'Macro lead — cross-asset stance from packaged snapshots',
        'claude-sonnet-4-6',
        'gpt-5',
        'agents/macro-lead.md',
        true
    )
ON CONFLICT (id) DO UPDATE SET
    model_default     = EXCLUDED.model_default,
    constitution_path = EXCLUDED.constitution_path,
    active            = true,
    updated_at        = now();
