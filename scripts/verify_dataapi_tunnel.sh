#!/usr/bin/env bash
# Verify Data API reachability via Cloudflare Tunnel (or local loopback on the server).
#
# Usage (any machine with outbound HTTPS):
#   bash scripts/verify_dataapi_tunnel.sh
#
# Override the public URL (legacy hostname):
#   DATAAPI_TUNNEL_URL=https://dataapi.theeyebeta.store bash scripts/verify_dataapi_tunnel.sh
#
# Authenticated smoke test (reads ADMIN_DATAAPI_* from .env when set):
#   bash scripts/verify_dataapi_tunnel.sh --auth
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

DATAAPI_TUNNEL_URL="${DATAAPI_TUNNEL_URL:-https://dataapiprod.theeyebeta.store}"
DATAAPI_LOCAL_URL="${DATAAPI_LOCAL_URL:-http://127.0.0.1:7000}"
RUN_AUTH=0

for arg in "$@"; do
  case "$arg" in
    --auth) RUN_AUTH=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$ENV_FILE" && set +a
fi

pass() { echo "  OK   $*"; }
fail() { echo "  FAIL $*" >&2; exit 1; }

echo "══════════════════════════════════════════════════════════════"
echo "  Data API tunnel connectivity"
echo "══════════════════════════════════════════════════════════════"
echo
echo "Public URL : ${DATAAPI_TUNNEL_URL}"
echo "Local URL  : ${DATAAPI_LOCAL_URL} (server only)"
echo

echo "▶ [1/3] Local health (skipped when not on server)"
if curl -fsS --max-time 5 "${DATAAPI_LOCAL_URL}/health" >/dev/null 2>&1; then
  pass "${DATAAPI_LOCAL_URL}/health"
else
  echo "  SKIP not reachable from this host (expected off-server)"
fi

echo
echo "▶ [2/3] Tunnel health"
HEALTH_JSON="$(curl -fsS --max-time 15 "${DATAAPI_TUNNEL_URL}/health")" \
  || fail "${DATAAPI_TUNNEL_URL}/health"
echo "  ${HEALTH_JSON}" | sed 's/^/       /'
pass "${DATAAPI_TUNNEL_URL}/health"

echo
echo "▶ [3/3] Authenticated API"
if [[ "$RUN_AUTH" -ne 1 ]]; then
  echo "  SKIP pass --auth to test service-token + quotes (needs ADMIN_DATAAPI_CLIENT_ID/SECRET)"
else
  client_id="${ADMIN_DATAAPI_CLIENT_ID:-${SERVICE_CLIENT_ID:-}}"
  client_secret="${ADMIN_DATAAPI_CLIENT_SECRET:-${SERVICE_CLIENT_SECRET:-}}"
  if [[ -z "$client_id" || -z "$client_secret" ]]; then
    fail "Set ADMIN_DATAAPI_CLIENT_ID and ADMIN_DATAAPI_CLIENT_SECRET in .env (or SERVICE_CLIENT_*)"
  fi

  token_response="$(curl -fsS -X POST "${DATAAPI_TUNNEL_URL}/api/v1/auth/service-token" \
    -u "${client_id}:${client_secret}" \
    -H "Content-Type: application/json" \
    -d '{"requested_scopes":["market:read","advisor:read"]}')"
  token="$(echo "$token_response" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
  [[ -n "$token" ]] || fail "service-token response missing access_token"

  pass "POST /api/v1/auth/service-token"

  curl -fsS "${DATAAPI_TUNNEL_URL}/api/v1/market-data/quotes?symbols=AAPL" \
    -H "Authorization: Bearer ${token}" >/dev/null \
    || fail "GET /api/v1/market-data/quotes"
  pass "GET /api/v1/market-data/quotes?symbols=AAPL"
fi

echo
echo "══════════════════════════════════════════════════════════════"
echo "  Tunnel OK — use DATAAPI_TUNNEL_URL=${DATAAPI_TUNNEL_URL}"
echo "  Admin service: ADMIN_DATAAPI_URL=${DATAAPI_TUNNEL_URL}"
echo "══════════════════════════════════════════════════════════════"
