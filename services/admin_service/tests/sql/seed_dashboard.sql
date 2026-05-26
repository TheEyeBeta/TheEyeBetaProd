-- Dashboard integration seed — exercises all four stat cards in one DSN.
-- Idempotent so it can be re-run alongside the other admin seed files.

-- 1. Pending orders + reference accounts/portfolios.
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '990e8400-e29b-41d4-a716-446655440080',
    'admin-dashboard-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name)
VALUES (
    'bb0e8400-e29b-41d4-a716-446655440080',
    '990e8400-e29b-41d4-a716-446655440080',
    'admin-dashboard-test'
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
    'cc0e8400-e29b-41d4-a716-446655440081'::uuid,
    'dash-pending-001',
    'bb0e8400-e29b-41d4-a716-446655440080'::uuid,
    i.id,
    'buy',
    'limit',
    7.0,
    175.0,
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
    limit_price,
    status,
    metadata
)
SELECT
    'cc0e8400-e29b-41d4-a716-446655440082'::uuid,
    'dash-pending-002',
    'bb0e8400-e29b-41d4-a716-446655440080'::uuid,
    i.id,
    'sell',
    'limit',
    3.0,
    180.0,
    'pending_approval',
    '{}'::jsonb
  FROM theeyebeta.instruments i
 WHERE i.symbol = 'AAPL'
ON CONFLICT (id) DO UPDATE
   SET status = 'pending_approval',
       metadata = '{}'::jsonb,
       updated_at = now();

-- 2. Active + inactive agents.
INSERT INTO theeyebeta.agents (
    id, department, role, model_default, model_fallback,
    constitution_path, active
) VALUES
    ('dash-agent-active-1', 'research', 'analyst',
     'gpt-5', 'gpt-4.1', 'agents/technical-analyst.md', TRUE),
    ('dash-agent-active-2', 'execution', 'trader',
     'gpt-5', 'gpt-4.1', 'agents/technical-analyst.md', TRUE),
    ('dash-agent-inactive', 'research', 'analyst',
     'gpt-5', 'gpt-4.1', 'agents/technical-analyst.md', FALSE)
ON CONFLICT (id) DO UPDATE
   SET active = EXCLUDED.active;

-- 3. Costs incurred today (UTC) — both LLM (model_runs) and vendor (api_costs).
INSERT INTO theeyebeta.agent_runs (
    id, agent_id, triggered_by, started_at, ended_at, status
)
VALUES (
    'ee0e8400-e29b-41d4-a716-446655440091',
    'dash-agent-active-1',
    'orchestrator',
    now(),
    now() + interval '5 seconds',
    'succeeded'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.model_runs (
    id, run_id, provider, model, input_tokens, output_tokens,
    cost_usd, status, kind, created_at
)
VALUES (
    'ee0e8400-e29b-41d4-a716-446655440092'::uuid,
    'ee0e8400-e29b-41d4-a716-446655440091'::uuid,
    'openai',
    'gpt-5',
    1000,
    500,
    1.5000,
    'success',
    'completion',
    now()
)
ON CONFLICT (id) DO UPDATE
   SET created_at = EXCLUDED.created_at,
       cost_usd = EXCLUDED.cost_usd;

INSERT INTO theeyebeta.api_costs (ts, vendor, category, cost_usd, detail)
VALUES (CURRENT_DATE, 'polygon', 'market_data', 0.5000, '{}'::jsonb)
ON CONFLICT (ts, vendor, category) DO UPDATE
   SET cost_usd = EXCLUDED.cost_usd;

-- 4. Audit checkpoint so the audit-verify card has a "last sealed" timestamp.
SELECT theeyebeta.ensure_audit_partitions(2);

INSERT INTO theeyebeta.audit_log (
    ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash
)
VALUES (
    now() - interval '15 minutes',
    'seed',
    'submit.order',
    'order',
    'cc0e8400-e29b-41d4-a716-446655440081',
    '{}'::jsonb,
    NULL,
    digest('dash-seed-row-1', 'sha256')
);

INSERT INTO theeyebeta.audit_checkpoints (
    checkpoint_id, last_row_id, last_row_hash, signature, signing_ts, row_count, s3_uri
)
VALUES (
    'dash-2026-05-25',
    1,
    digest('dash-checkpoint-hash', 'sha256'),
    digest('ed25519-dash-placeholder', 'sha256'),
    now() - interval '5 minutes',
    1,
    's3://theeyebeta-snapshots/checkpoints/dash-2026-05-25.json'
)
ON CONFLICT (checkpoint_id) DO NOTHING;
