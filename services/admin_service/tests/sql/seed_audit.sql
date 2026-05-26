-- Admin audit API integration seed.

SELECT theeyebeta.ensure_audit_partitions(2);

INSERT INTO theeyebeta.audit_log (
    ts,
    actor,
    action,
    entity_type,
    entity_id,
    payload,
    prev_hash,
    row_hash
)
VALUES (
    now() - interval '2 hours',
    'admin-api:test-operator',
    'approve.order',
    'order',
    'cc0e8400-e29b-41d4-a716-446655440001',
    '{"note": "seed"}'::jsonb,
    NULL,
    digest('seed-audit-row-1', 'sha256')
),
(
    now() - interval '1 hour',
    'oms',
    'submit.order',
    'order',
    'cc0e8400-e29b-41d4-a716-446655440002',
    '{}'::jsonb,
    NULL,
    digest('seed-audit-row-2', 'sha256')
),
(
    now() - interval '30 minutes',
    'admin-api:other',
    'reject.order',
    'order',
    'cc0e8400-e29b-41d4-a716-446655440003',
    '{"rejection_reason": "test"}'::jsonb,
    NULL,
    digest('seed-audit-row-3', 'sha256')
);

INSERT INTO theeyebeta.audit_checkpoints (
    checkpoint_id,
    last_row_id,
    last_row_hash,
    signature,
    signing_ts,
    row_count,
    s3_uri
)
VALUES (
    '2026-05-24',
    3,
    digest('checkpoint-hash', 'sha256'),
    digest('ed25519-sig-placeholder', 'sha256'),
    now() - interval '1 day',
    3,
    's3://theeyebeta-snapshots/checkpoints/2026-05-24.json'
)
ON CONFLICT (checkpoint_id) DO NOTHING;
