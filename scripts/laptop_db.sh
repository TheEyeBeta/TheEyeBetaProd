#!/usr/bin/env bash
# Connect to production PostgreSQL over Tailscale from a dev laptop.
#
# Setup (once on laptop): see docs/tailscale-db-setup.md
#   cp .env.laptop.example .env.laptop
#   # set TB_APP_PASSWORD in .env.laptop (match the server .env)
#
# Usage:
#   ./scripts/laptop_db.sh check     # verify Tailscale + DB read/write
#   ./scripts/laptop_db.sh psql      # interactive psql session
#   ./scripts/laptop_db.sh env       # print export statements
#   eval "$(./scripts/laptop_db.sh env)"   # load DATABASE_URL in current shell
#   make laptop-db-check
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.laptop}"

THEEYEBETA_DB_HOST="${THEEYEBETA_DB_HOST:-the-eye-beta-server}"
THEEYEBETA_DB_PORT="${THEEYEBETA_DB_PORT:-5432}"
THEEYEBETA_DB_NAME="${THEEYEBETA_DB_NAME:-TheEyeBeta2025Live}"
THEEYEBETA_DB_USER="${THEEYEBETA_DB_USER:-tb_app}"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  check   Verify Tailscale is up and tb_app can read/write the remote database
  psql    Open an interactive psql session (requires psql client)
  env     Print shell exports for DATABASE_URL and related vars
  url     Print the plain postgresql:// connection URL (password masked)

Setup:
  cp .env.laptop.example .env.laptop
  # Edit .env.laptop — set TB_APP_PASSWORD to match the server

Makefile:
  make laptop-db-setup   # copy .env.laptop.example if missing
  make laptop-db-check   # run check
  make laptop-db-psql    # run psql
  make laptop-db-env     # eval-friendly exports
EOF
}

load_config() {
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Missing $ENV_FILE" >&2
        echo "Run: cp .env.laptop.example .env.laptop && edit TB_APP_PASSWORD" >&2
        exit 1
    fi
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a

    if [[ -z "${TB_APP_PASSWORD:-}" || "$TB_APP_PASSWORD" == "CHANGE_ME" ]]; then
        echo "Set TB_APP_PASSWORD in $ENV_FILE (must match the server)" >&2
        exit 1
    fi

    APP_URL="postgresql://${THEEYEBETA_DB_USER}:${TB_APP_PASSWORD}@${THEEYEBETA_DB_HOST}:${THEEYEBETA_DB_PORT}/${THEEYEBETA_DB_NAME}"
    DATABASE_URL="postgresql+psycopg://${THEEYEBETA_DB_USER}:${TB_APP_PASSWORD}@${THEEYEBETA_DB_HOST}:${THEEYEBETA_DB_PORT}/${THEEYEBETA_DB_NAME}"
    INGEST_DATABASE_URL="$APP_URL"
    TAILSCALE_DATABASE_URL="$APP_URL"
}

tcp_reachable() {
    local host="$1" port="$2"
    if command -v nc >/dev/null 2>&1; then
        nc -z -w 3 "$host" "$port" >/dev/null 2>&1
        return
    fi
    timeout 3 bash -c "echo >/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

cmd_check() {
    local fail=0
    pass() { printf '  OK  %s\n' "$1"; }
    warn() { printf '  WARN %s\n' "$1"; }
    fail_msg() { printf '  FAIL %s\n' "$1"; fail=1; }

    load_config

    echo "=== Laptop → Tailscale PostgreSQL ==="
    echo "Target: ${THEEYEBETA_DB_HOST}:${THEEYEBETA_DB_PORT}/${THEEYEBETA_DB_NAME}"
    echo

    if ! command -v tailscale >/dev/null 2>&1; then
        fail_msg "tailscale CLI not found — install from https://tailscale.com/download"
    else
        pass "tailscale CLI present"
    fi

    local self_ip=""
    if command -v tailscale >/dev/null 2>&1; then
        self_ip="$(tailscale ip -4 2>/dev/null || true)"
        if [[ -z "$self_ip" ]]; then
            fail_msg "Tailscale not connected on this laptop (run: tailscale up)"
        else
            pass "Tailscale connected (this device: $self_ip)"
        fi
    fi

    if command -v tailscale >/dev/null 2>&1; then
        local server_online=""
        server_online="$(tailscale status 2>/dev/null | grep -F "$THEEYEBETA_DB_HOST" || true)"
        if [[ -z "$server_online" ]]; then
            warn "peer '$THEEYEBETA_DB_HOST' not listed — is the server online in your tailnet?"
        else
            pass "server peer visible: ${server_online%% *}"
        fi
    fi

    if tcp_reachable "$THEEYEBETA_DB_HOST" "$THEEYEBETA_DB_PORT"; then
        pass "TCP ${THEEYEBETA_DB_HOST}:${THEEYEBETA_DB_PORT} reachable"
    else
        fail_msg "cannot reach ${THEEYEBETA_DB_HOST}:${THEEYEBETA_DB_PORT} (Tailscale down or ACL blocking 5432)"
    fi

    if ! command -v psql >/dev/null 2>&1; then
        fail_msg "psql client not found — install postgresql-client"
    else
        pass "psql client present"
    fi

    if command -v psql >/dev/null 2>&1; then
        if ! psql "$APP_URL" -tAc "SELECT count(*) FROM theeyebeta.agents" >/dev/null 2>&1; then
            fail_msg "tb_app read failed (wrong password or pg_hba)"
        else
            pass "tb_app read (theeyebeta.agents)"
        fi

        if ! psql "$APP_URL" -c \
            "CREATE TEMP TABLE _laptop_rw_probe(val int); INSERT INTO _laptop_rw_probe VALUES (1);" \
            >/dev/null 2>&1; then
            fail_msg "tb_app write failed"
        else
            pass "tb_app write (temp table)"
        fi
    fi

    echo
    if [[ "$fail" -ne 0 ]]; then
        echo "Checks failed. Fix Tailscale connectivity or credentials, then re-run:"
        echo "  make laptop-db-check"
        exit 1
    fi
    echo "All checks passed. Load env in your shell:"
    echo "  eval \"\$(./scripts/laptop_db.sh env)\""
}

cmd_env() {
    load_config
    printf 'export THEEYEBETA_DB_HOST=%q\n' "$THEEYEBETA_DB_HOST"
    printf 'export THEEYEBETA_DB_PORT=%q\n' "$THEEYEBETA_DB_PORT"
    printf 'export THEEYEBETA_DB_NAME=%q\n' "$THEEYEBETA_DB_NAME"
    printf 'export THEEYEBETA_DB_USER=%q\n' "$THEEYEBETA_DB_USER"
    printf 'export TB_APP_PASSWORD=%q\n' "$TB_APP_PASSWORD"
    printf 'export DATABASE_URL=%q\n' "$DATABASE_URL"
    printf 'export INGEST_DATABASE_URL=%q\n' "$INGEST_DATABASE_URL"
    printf 'export TAILSCALE_DATABASE_URL=%q\n' "$TAILSCALE_DATABASE_URL"
    if [[ -n "${POSTGRES_SCHEMA:-}" ]]; then
        printf 'export POSTGRES_SCHEMA=%q\n' "$POSTGRES_SCHEMA"
    fi
    if [[ -n "${TB_RND_PASSWORD:-}" ]]; then
        printf 'export TB_RND_PASSWORD=%q\n' "$TB_RND_PASSWORD"
    fi
}

cmd_url() {
    load_config
    local masked="${APP_URL//:${TB_APP_PASSWORD}@/:****@}"
    echo "$masked"
}

cmd_psql() {
    load_config
    exec psql "$APP_URL"
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        check) cmd_check ;;
        env) cmd_env ;;
        url) cmd_url ;;
        psql) cmd_psql ;;
        -h | --help | help | "") usage; [[ -z "$cmd" ]] && exit 1 || exit 0 ;;
        *)
            echo "Unknown command: $cmd" >&2
            usage
            exit 1
            ;;
    esac
}

main "$@"
