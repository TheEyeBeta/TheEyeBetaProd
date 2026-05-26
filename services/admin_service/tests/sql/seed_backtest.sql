-- Admin backtest API integration seed.

INSERT INTO theeyebeta.strategies (id, name, description, config, active)
VALUES
    (
        'momentum-v1',
        'Momentum v1',
        'Test strategy for backtest router integration tests',
        '{}'::jsonb,
        true
    )
ON CONFLICT (id) DO UPDATE
   SET name = EXCLUDED.name,
       description = EXCLUDED.description,
       config = EXCLUDED.config,
       active = true;

INSERT INTO theeyebeta.backtest_runs (
    id, strategy_id, start_date, end_date, universe, config, git_sha,
    started_at, ended_at, status, result_blob_uri
)
VALUES
    (
        'cc111111-1111-1111-1111-111111111111',
        'momentum-v1',
        DATE '2024-01-01',
        DATE '2024-03-31',
        'sp500',
        '{"walk_forward": false}'::jsonb,
        'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
        now() - interval '6 hours',
        now() - interval '5 hours',
        'succeeded',
        's3://theeyebeta-backtest/cc111111.parquet'
    ),
    (
        'cc222222-2222-2222-2222-222222222222',
        'momentum-v1',
        DATE '2024-04-01',
        DATE '2024-06-30',
        'sp500',
        '{"walk_forward": true}'::jsonb,
        'cafebabecafebabecafebabecafebabecafebabe',
        now() - interval '2 hours',
        NULL,
        'running',
        NULL
    )
ON CONFLICT (id) DO NOTHING;
