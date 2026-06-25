-- Intelligence control integration seed.

INSERT INTO theeyebeta.admin_briefings (id, title, status, summary, stale_after)
VALUES
  (
    'aa111111-1111-1111-1111-111111111111',
    'Daily operator briefing',
    'ready',
    'Markets open; risk within limits.',
    now() + interval '1 day'
  ),
  (
    'aa222222-2222-2222-2222-222222222222',
    'Weekly strategy digest',
    'stale',
    'Superseded by newer run.',
    now() - interval '1 day'
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO theeyebeta.admin_cost_state (id, kill_switch_active)
VALUES (1, false)
ON CONFLICT (id) DO NOTHING;
