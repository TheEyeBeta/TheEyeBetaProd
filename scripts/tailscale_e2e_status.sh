#!/usr/bin/env bash
# End-to-end Tailscale database access status (server + what the laptop still needs).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

echo "══════════════════════════════════════════════════════════════"
echo "  Tailscale DB — end-to-end status"
echo "══════════════════════════════════════════════════════════════"
echo

echo "▶ Server (Mac mini / the-eye-beta-server)"
if bash "$SCRIPT_DIR/verify_tailscale_db.sh"; then
    server_ok=1
else
    server_ok=0
fi

echo
echo "▶ Tailnet peers (laptop must appear here for remote access)"
peer_lines="$(tailscale status 2>/dev/null | grep -v '^#' | grep -v '^$' | grep -v "$(tailscale ip -4 2>/dev/null || echo IMPOSSIBLE)" || true)"
if [[ -z "$peer_lines" ]]; then
    echo "  PENDING  No other devices on your tailnet yet."
    echo "           Install Tailscale on your laptop and sign in with the same account."
    laptop_ok=0
else
    echo "$peer_lines" | while read -r line; do
        echo "  OK       Peer: $line"
    done
    laptop_ok=1
fi

ts_host="${THEEYEBETA_DB_HOST:-the-eye-beta-server}"
db_name="${THEEYEBETA_DB_NAME:-TheEyeBeta2025Live}"

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" && set +a
fi

echo
echo "▶ Laptop checklist (run on your laptop, in a clone of this repo)"
echo "  1. Install Tailscale → https://tailscale.com/download"
echo "  2. Sign in with the same tailnet as this server"
echo "  3. make laptop-db-setup"
if [[ -n "${TB_APP_PASSWORD:-}" ]]; then
    echo "  4. Edit .env.laptop → TB_APP_PASSWORD must match server (currently set on server)"
else
    echo "  4. Edit .env.laptop → set TB_APP_PASSWORD to match server .env"
fi
echo "  5. make laptop-db-check"
echo "  6. make laptop-db-psql   # or use TablePlus / DBeaver with:"
echo "       Host: $ts_host   Port: 5432   DB: $db_name   User: tb_app"
echo
echo "  Data stays on the server — laptop only connects remotely."
echo

if [[ "$server_ok" -ne 1 ]]; then
    echo "══════════════════════════════════════════════════════════════"
    echo "  INCOMPLETE — fix server checks above, then complete laptop steps."
    echo "══════════════════════════════════════════════════════════════"
    exit 1
fi

echo "══════════════════════════════════════════════════════════════"
if [[ "$laptop_ok" -eq 1 ]]; then
    echo "  READY — server OK and at least one remote peer is online."
    echo "  Run 'make laptop-db-check' on your laptop to confirm."
else
    echo "  SERVER READY — Mac mini is fully configured."
    echo "  Laptop PENDING — complete the steps above on your computer."
fi
echo "══════════════════════════════════════════════════════════════"
exit 0
