-- Seed data for control-plane API integration tests.

INSERT INTO theeyebeta.worker_runs
    (worker_name, worker_type, trade_date, run_type, status, started_at, ended_at, records_written)
VALUES
    ('MassiveDailyIngestionWorker', 'worker', CURRENT_DATE - 1, 'scheduled', 'COMPLETED',
     now() - interval '2 hours', now() - interval '1 hour', 500),
    ('IntradayIngestionWorker', 'worker', CURRENT_DATE, 'scheduled', 'COMPLETED',
     now() - interval '30 minutes', now() - interval '25 minutes', 120),
    ('GapSentinelWorker', 'worker', CURRENT_DATE, 'scheduled', 'FAILED',
     now() - interval '3 hours', now() - interval '2 hours', 0);

INSERT INTO theeyebeta.worker_heartbeats
    (worker_id, worker_type, status, last_heartbeat)
VALUES
    ('MassiveDailyIngestionWorker', 'worker', 'stopped', now() - interval '1 hour'),
    ('IntradayIngestionWorker', 'worker', 'running', now() - interval '10 minutes'),
    ('GapSentinelWorker', 'worker', 'failed', now() - interval '3 days')
ON CONFLICT (worker_id) DO UPDATE SET
    last_heartbeat = EXCLUDED.last_heartbeat,
    status = EXCLUDED.status;

UPDATE theeyebeta.trask_circuit_breakers
   SET state = 'open', failure_count = 3, opened_at = now() - interval '10 minutes'
 WHERE component_id = 'GapSentinelWorker_sentinel';

UPDATE theeyebeta.trask_components
   SET state = 'DEGRADED', last_heartbeat = now() - interval '1 hour'
 WHERE component_id = 'GapSentinelWorker';

INSERT INTO theeyebeta.audit_alerts
    (alert_type, severity, trade_date, worker_name, title, message, created_at)
VALUES
    ('gap_detected', 'CRITICAL', CURRENT_DATE, 'GapSentinelWorker',
     'Critical gap', 'Missing EOD bars for 3 symbols', now() - interval '1 hour'),
    ('pipeline_warn', 'WARN', CURRENT_DATE, 'MacroIngestionWorker',
     'Macro lag', 'FRED series delayed', now() - interval '2 hours');

INSERT INTO theeyebeta.prelive_check_cache (run_at, overall, checks)
VALUES (
    now() - interval '1 hour',
    'pass',
    '[{"name":"MIGRATION HEADS","status":"pass","detail":"ok","value":null}]'::jsonb
);

INSERT INTO theeyebeta.admin_users (username, email, password_bcrypt, is_active)
VALUES (
    'analyst-user',
    'analyst@test.local',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
    true
)
ON CONFLICT (username) DO NOTHING;

INSERT INTO theeyebeta.admin_user_roles (user_id, role_id)
SELECT u.id, r.id
  FROM theeyebeta.admin_users u
  CROSS JOIN theeyebeta.admin_roles r
 WHERE u.username = 'analyst-user' AND r.name = 'ANALYST'
ON CONFLICT DO NOTHING;
