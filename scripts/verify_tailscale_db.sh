#!/usr/bin/env bash
# Verify end-to-end Tailscale PostgreSQL access (read/write via tb_app).
# Run on the database host after Tailscale and pg_hba are configured.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd/.env}"
FAIL=0

pass() { printf '  OK  %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAIL=1; }

echo "=== Tailscale PostgreSQL verification ==="

if ! command -v tailscale >/dev/null 2>&1; then
    fail "tailscale CLI not found"
else
    pass "tailscale CLI present"
fi

ts_ip="$(tailscale ip -4 2>/dev/null || true)"
ts_host="$(tailscale status --json 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('Self') or {}).get('DNSName','').rstrip('.'))" \
    2>/dev/null || true)"
if [[ -z "$ts_ip" ]]; then
    fail "Tailscale is not connected (no IPv4 address)"
else
    pass "Tailscale IPv4: $ts_ip"
fi
if [[ -n "$ts_host" ]]; then
    pass "MagicDNS hostname: $ts_host"
fi

peer_count="$(tailscale status --json 2>/dev/null \
    | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('Peer',{})))" \
    2>/dev/null || echo 0)"
if [[ "$peer_count" -eq 0 ]]; then
    echo "  WARN no other tailnet peers online — remote clients must join the same tailnet"
else
    pass "$peer_count tailnet peer(s) visible"
fi

if ! ss -tln | grep -q ':5432'; then
    fail "nothing listening on TCP 5432"
else
    pass "PostgreSQL listening on :5432"
fi

if [[ ! -f "$ENV_FILE" ]]; then
    fail "env file missing: $ENV_FILE"
    exit 1
fi

# shellcheck disable=SC1090
set -a && source "$ENV_FILE" && set +a

admin_url="${DATABASE_URL/postgresql+psycopg/postgresql}"
admin_url="${admin_url/postgresql+asyncpg/postgresql}"
if [[ -z "${admin_url:-}" ]]; then
    fail "DATABASE_URL not set in $ENV_FILE"
else
    pass "DATABASE_URL loaded"
fi

if ! psql "$admin_url" -tAc "SELECT 1" >/dev/null 2>&1; then
    fail "admin connection via localhost failed"
else
    pass "admin connection via localhost"
fi

hba_ok="$(psql "$admin_url" -tAc \
    "SELECT count(*) FROM pg_hba_file_rules WHERE type='host' AND address='100.64.0.0' AND netmask='255.192.0.0'")"
if [[ "$hba_ok" -lt 1 ]]; then
    fail "pg_hba missing Tailscale rule (host all all 100.64.0.0/10 scram-sha-256)"
else
    pass "pg_hba allows Tailscale CGNAT range 100.64.0.0/10"
fi

listen="$(psql "$admin_url" -tAc "SHOW listen_addresses;")"
if [[ "$listen" == "*" || "$listen" == *"$ts_ip"* ]]; then
    pass "listen_addresses=$listen"
else
    fail "listen_addresses=$listen (expected * or to include $ts_ip)"
fi

if [[ -z "${TB_APP_PASSWORD:-}" ]]; then
    fail "TB_APP_PASSWORD not set in $ENV_FILE"
else
    pass "TB_APP_PASSWORD set"
fi

db_name="$(psql "$admin_url" -tAc "SELECT current_database();")"
app_url="postgresql://tb_app:${TB_APP_PASSWORD}@${ts_ip}:5432/${db_name}"

if ! psql "$app_url" -tAc "SELECT count(*) FROM theeyebeta.agents" >/dev/null 2>&1; then
    fail "tb_app read via Tailscale IP failed"
else
    pass "tb_app read via Tailscale IP"
fi

if ! psql "$app_url" -c "CREATE TEMP TABLE _tailscale_rw_probe(val int); INSERT INTO _tailscale_rw_probe VALUES (1);" >/dev/null 2>&1; then
    fail "tb_app write via Tailscale IP failed"
else
    pass "tb_app write via Tailscale IP"
fi

if [[ -n "$ts_host" ]]; then
    dns_url="postgresql://tb_app:${TB_APP_PASSWORD}@${ts_host}:5432/${db_name}"
    if psql "$dns_url" -tAc "SELECT 1" >/dev/null 2>&1; then
        pass "tb_app connection via MagicDNS ($ts_host)"
    else
        fail "tb_app connection via MagicDNS ($ts_host)"
    fi
fi

echo
echo "=== Remote client connection (from any device on your tailnet) ==="
echo "Host:     ${ts_host:-$ts_ip}"
echo "Port:     5432"
echo "Database: ${db_name}"
echo "User:     tb_app  (read/write on theeyebeta; audit_log is append-only)"
echo "URL:      postgresql://tb_app:<TB_APP_PASSWORD>@${ts_host:-$ts_ip}:5432/${db_name}"
echo
echo "Quick test from your laptop (with Tailscale connected):"
echo "  psql \"postgresql://tb_app:<TB_APP_PASSWORD>@${ts_host:-$ts_ip}:5432/${db_name}\" -c 'SELECT count(*) FROM theeyebeta.agents;'"
echo

if [[ "$FAIL" -ne 0 ]]; then
    echo "One or more checks failed."
    exit 1
fi
echo "All checks passed."
