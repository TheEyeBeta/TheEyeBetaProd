#!/usr/bin/env bash
# Nightly logical backup of the theeyebeta database (pg_dump custom format).
# Retains the newest seven dumps; never deletes when fewer than two exist.
# Reads DATABASE_URL from the Prod .env (psql-compatible, dialect stripped).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/home/the-eye-beta/backups}"
ENV_FILE="${ENV_FILE:-/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd/.env}"
RETENTION_COUNT="${RETENTION_COUNT:-7}"
LOG_FILE="$BACKUP_DIR/backup.log"
LOCK_FILE="$BACKUP_DIR/.backup.lock"

started_epoch="$(date +%s)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >&2
}

database_url() {
    local url
    url="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
    url="${url/postgresql+psycopg/postgresql}"
    url="${url/postgresql+asyncpg/postgresql}"
    printf '%s' "$url"
}

write_failure_alert() {
    local msg="$1"
    local url
    url="$(database_url 2>/dev/null || true)"
    if [[ -z "$url" ]]; then
        log "cannot write audit alert: DATABASE_URL missing"
        return 1
    fi
    local safe_msg
    safe_msg="${msg//\'/\'\'}"
    psql "$url" -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL || log "audit alert insert failed (DB unreachable?)"
INSERT INTO public.audit_alerts
    (alert_type, severity, worker_name, title, message, metadata)
VALUES (
    'BACKUP_FAILURE',
    'CRITICAL',
    'backup_db.sh',
    'Database backup failed',
    '${safe_msg}',
    jsonb_build_object(
        'script', 'backup_db.sh',
        'started_at', '${started_at}',
        'backup_dir', '${BACKUP_DIR}'
    )
);
SQL
}

fail() {
    local msg="$1"
    log "FAILURE: $msg"
    write_failure_alert "$msg" || true
    exit 1
}

if [[ ! -f "$ENV_FILE" ]]; then
    fail "ENV_FILE not found: $ENV_FILE"
fi

url="$(database_url)"
if [[ -z "$url" ]]; then
    fail "DATABASE_URL not found in $ENV_FILE"
fi

mkdir -p "$BACKUP_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another backup is already running (lock held), exiting"
    exit 0
fi

stamp="$(date -u +%Y%m%d-%H%M)"
out="$BACKUP_DIR/theeye-${stamp}.dump"
partial="${out}.partial"

if [[ -f "$partial" ]]; then
    rm -f "$partial"
fi

log "starting pg_dump -> $out"
if ! pg_dump --format=custom --no-owner --file="$partial" "$url"; then
    rm -f "$partial"
    fail "pg_dump exited non-zero"
fi

if ! mv "$partial" "$out"; then
    rm -f "$partial"
    fail "failed to finalize dump at $out"
fi

size_bytes="$(stat -c '%s' "$out")"
size_human="$(du -h "$out" | cut -f1)"
duration_s="$(( $(date +%s) - started_epoch ))"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '%s size_bytes=%s size_human=%s duration_s=%s path=%s\n' \
    "$finished_at" "$size_bytes" "$size_human" "$duration_s" "$out" >>"$LOG_FILE"

log "backup written: $out ($size_human, ${duration_s}s)"

mapfile -t dumps < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f \
        \( -name 'theeye-*.dump' -o -name 'theeyebeta-*.dump' \) \
        -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-
)
dump_count="${#dumps[@]}"
if (( dump_count >= 2 && dump_count > RETENTION_COUNT )); then
    for (( idx = RETENTION_COUNT; idx < dump_count; idx++ )); do
        rm -f "${dumps[$idx]}"
        log "retention: removed ${dumps[$idx]}"
    done
elif (( dump_count > 0 )); then
    log "retention: keeping ${dump_count} dump(s) (guard: need >=2 before pruning)"
fi

log "backup completed successfully"
