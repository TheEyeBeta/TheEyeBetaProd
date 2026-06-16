# Disaster Recovery

## Backup schedule

`theeye-backup.timer` runs daily at 02:00 UTC.

## Restore drill

Run `scripts/test_restore.sh` (creates `theeyebeta_restore_test`, validates schema and row counts).

### Manual restore steps

1. Stop writers: `tb stop workers` / pause systemd timers
2. Restore latest backup to staging DB
3. `uv run alembic -c db/alembic.ini check`
4. Compare row counts: `orders`, `audit_log`, `worker_runs`, `prices`, `accounts`
5. Drop staging DB after sign-off

## RPO / RTO targets

| Metric | Target |
|--------|--------|
| RPO | 24 hours (daily backup) |
| RTO | 4 hours (manual restore + service restart) |

## Contacts

Document on-call rotation in sops-managed secrets — never commit PII here.
