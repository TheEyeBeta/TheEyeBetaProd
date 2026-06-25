-- Workers control plane integration seed (public audit tables + sample runs).

INSERT INTO public.audit_worker_runs (
    worker_name, worker_type, trade_date, run_type, status,
    started_at, ended_at, duration_seconds, records_written, records_expected
)
VALUES
(
    'GapSentinelWorker', 'system', CURRENT_DATE, 'scheduled', 'COMPLETED',
    now() - interval '3 hours', now() - interval '2 hours 50 minutes', 600, 12, 12
),
(
    'GapSentinelWorker', 'system', CURRENT_DATE - 1, 'scheduled', 'FAILED',
    now() - interval '1 day', now() - interval '1 day' + interval '5 minutes', 300, 0, 12
),
(
    'MassiveDailyIngestionWorker', 'system', CURRENT_DATE, 'scheduled', 'COMPLETED',
    now() - interval '6 hours', now() - interval '5 hours 30 minutes', 1800, 500, 500
),
(
    'daily_pipeline', 'system', CURRENT_DATE, 'scheduled', 'COMPLETED',
    now() - interval '5 hours', now() - interval '4 hours 45 minutes', 900, 4, 4
);

INSERT INTO public.worker_heartbeats (
    worker_id, worker_type, status, last_heartbeat, started_at, last_error
)
VALUES
(
    'GapSentinelWorker', 'system', 'stopped', now() - interval '2 hours', now() - interval '3 hours', NULL
),
(
    'MassiveDailyIngestionWorker', 'system', 'stopped', now() - interval '5 hours', now() - interval '6 hours', NULL
)
ON CONFLICT (worker_id) DO UPDATE SET
    status = EXCLUDED.status,
    last_heartbeat = EXCLUDED.last_heartbeat;
