INSERT INTO theeyebeta.strategies (id, name, description, config, active) VALUES
(
    'example_swing_us',
    'Example US Swing',
    'Reference swing strategy for paper-trade smoke tests',
    '{"market":"US.NASDAQ","horizon_days":[5,30],"max_positions":10}'::jsonb,
    false
)
ON CONFLICT (id) DO NOTHING;
