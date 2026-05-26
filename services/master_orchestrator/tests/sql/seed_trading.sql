-- Trading seed for master-orchestrator integration tests.
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode)
VALUES (
    '770e8400-e29b-41d4-a716-446655440002',
    'mo-test-acct',
    'alpaca',
    'paper'
)
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name)
VALUES (
    '660e8400-e29b-41d4-a716-446655440001',
    '770e8400-e29b-41d4-a716-446655440002',
    'mo-integration-portfolio'
)
ON CONFLICT (id) DO NOTHING;
