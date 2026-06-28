#!/usr/bin/env bash
# Enable TheEyeBetaLocal engine + Trask + news parity on the Prod host.
#
# Usage:
#   sudo bash deploy/enable_local_parity_stack.sh          # dry-run
#   sudo bash deploy/enable_local_parity_stack.sh --confirm
#
set -euo pipefail

PROD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ROOT="${LOCAL_ROOT:-/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaLocal}"
RUN_USER="${SUDO_USER:-the-eye-beta}"
CONFIRM=0

for arg in "$@"; do
  case "$arg" in
    --confirm) CONFIRM=1 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

log() { echo "[local-parity] $*"; }
die() { echo "[local-parity] ERROR: $*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run with sudo"

[[ -d "$LOCAL_ROOT" ]] || die "Missing Local repo: $LOCAL_ROOT"
[[ -x "$LOCAL_ROOT/.venv/bin/python" ]] || die "Missing Local venv: $LOCAL_ROOT/.venv"
[[ -f "$LOCAL_ROOT/.env" ]] || die "Missing $LOCAL_ROOT/.env"

install_unit() {
  local src="$1"
  local name="$2"
  [[ -f "$src" ]] || die "Missing unit file: $src"
  log "Installing $name"
  cp "$src" "/etc/systemd/system/$name"
  chmod 644 "/etc/systemd/system/$name"
}

log "Prod root:  $PROD_ROOT"
log "Local root: $LOCAL_ROOT"
log "Run user:   $RUN_USER"

echo ""
echo "WARNING: This starts the Local trade engine (~1.5 GiB RAM) alongside Prod timers."
echo "         Engine writes public.* tables; Prod canonical schema is theeyebeta.*."
echo "         Review docs/ops/local-parity-migration.md before --confirm."
echo ""

UNITS=(
  "theeyebeta-engine.service"
  "theeyebeta-trask.service"
)

for unit in "${UNITS[@]}"; do
  src="$LOCAL_ROOT/scripts/systemd/$unit"
  if [[ ! -f "$src" ]]; then
    src="$PROD_ROOT/deploy/systemd/archived/$unit"
  fi
  if [[ "$CONFIRM" -eq 1 ]]; then
    install_unit "$src" "$unit"
    systemctl unmask "$unit" 2>/dev/null || true
  else
    log "DRY-RUN would install: $src → /etc/systemd/system/$unit"
  fi
done

if [[ "$CONFIRM" -eq 1 ]]; then
  systemctl daemon-reload
  for unit in "${UNITS[@]}"; do
    systemctl enable "$unit"
  done
  systemctl start theeyebeta-engine.service
  sleep 5
  systemctl start theeyebeta-trask.service
fi

PROD_UNITS=(
  "theeye-news-ingest.timer"
  "theeye-news-bridge.timer"
)
for unit in "${PROD_UNITS[@]}"; do
  src="$PROD_ROOT/deploy/systemd/${unit%.timer}.service"
  timer="$PROD_ROOT/deploy/systemd/$unit"
  [[ -f "$src" ]] || die "Missing $src"
  [[ -f "$timer" ]] || die "Missing $timer"
  if [[ "$CONFIRM" -eq 1 ]]; then
    install_unit "$src" "${unit%.timer}.service"
    install_unit "$timer" "$unit"
    systemctl enable "$unit"
  else
    log "DRY-RUN would enable: $unit"
  fi
done

THEEYE_SHIM="$PROD_ROOT/theeye"
if [[ "$CONFIRM" -eq 1 ]]; then
  install -m 755 "$PROD_ROOT/scripts/theeye_shim.sh" "$THEEYE_SHIM"
  log "Installed CLI shim: $THEEYE_SHIM"
else
  log "DRY-RUN would install theeye shim"
fi

if [[ "$CONFIRM" -eq 0 ]]; then
  echo ""
  echo "Dry-run complete. Re-run with --confirm to apply."
  exit 0
fi

if [[ "$CONFIRM" -eq 1 ]]; then
  systemctl daemon-reload
  systemctl start theeye-news-ingest.timer
  systemctl start theeye-news-bridge.timer
fi

echo ""
log "Status:"
systemctl is-active theeyebeta-engine.service || true
systemctl is-active theeyebeta-trask.service || true
systemctl is-active theeye-news-ingest.timer || true
systemctl is-active theeye-news-bridge.timer || true

echo ""
log "Done. Verify:"
echo "  curl -s http://127.0.0.1:8090/health"
echo "  cd $PROD_ROOT && ./theeye now status"
echo "  cd $PROD_ROOT && uv run tb trask status"
