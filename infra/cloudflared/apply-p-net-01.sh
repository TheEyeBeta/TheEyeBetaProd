#!/usr/bin/env bash
# P-NET-01 — Add admin.theeyebeta.store ingress to Cloudflare Tunnel
# Run this script on the Mac mini once it's back online:
#   bash infra/cloudflared/apply-p-net-01.sh
#
# Safe to re-run: backs up the existing config before touching it.

set -euo pipefail

CONFIG=/etc/cloudflared/config.yml
BACKUP="${CONFIG}.bak.$(date +%Y%m%d_%H%M%S)"

# ── 1. Backup ────────────────────────────────────────────────────────────────
echo "==> Backing up current config to ${BACKUP}"
sudo cp "$CONFIG" "$BACKUP"
echo "    OK: $(ls -lh "$BACKUP")"

# ── 2. Sanity-check: confirm admin block is not already present ───────────────
if grep -q "admin\.theeyebeta\.store" "$CONFIG"; then
  echo "WARN: admin.theeyebeta.store already present in config — no changes made."
  echo "      Current ingress section:"
  grep -A4 "admin" "$CONFIG"
  exit 0
fi

# ── 3. Show current ingress rules before editing ─────────────────────────────
echo ""
echo "==> Current ingress rules:"
grep -E "hostname:|service:|catch-all" "$CONFIG" || true
echo ""

# ── 4. Insert the new ingress block BEFORE the catch-all 404 rule ────────────
#    Uses Python so we don't depend on GNU sed behaviour differences on macOS.
echo "==> Inserting admin.theeyebeta.store ingress block..."
sudo python3 - "$CONFIG" <<'PYEOF'
import sys, pathlib, re

path = pathlib.Path(sys.argv[1])
text = path.read_text()

NEW_BLOCK = """\
  - hostname: admin.theeyebeta.store
    service: http://127.0.0.1:7200
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
      tlsTimeout: 30s
"""

# The catch-all rule has no hostname — it is the last ingress entry.
# Match: "  - service: http_status:404" or "  - service: http://..." with no hostname line above.
# Strategy: find the last "  - service:" line that has no preceding hostname on the same item.
CATCHALL = re.compile(r'^( {2}- service: http_status:404\b.*)', re.MULTILINE)

if not CATCHALL.search(text):
    # Fallback: look for any line that is exactly the catch-all sentinel
    CATCHALL = re.compile(r'^( {2}- service: .*)\n', re.MULTILINE)
    matches = list(CATCHALL.finditer(text))
    if not matches:
        print("ERROR: Could not locate catch-all ingress entry. Edit manually.", file=sys.stderr)
        sys.exit(1)
    match = matches[-1]  # last service entry is the catch-all
else:
    match = CATCHALL.search(text)

insert_pos = match.start()
new_text = text[:insert_pos] + NEW_BLOCK + "\n" + text[insert_pos:]
path.write_text(new_text)
print("    OK: block inserted.")
PYEOF

# ── 5. Show updated ingress section ──────────────────────────────────────────
echo ""
echo "==> Updated ingress rules:"
grep -E "hostname:|service:|catch-all" "$CONFIG" || true
echo ""

# ── 6. Validate ──────────────────────────────────────────────────────────────
echo "==> Validating tunnel ingress..."
cloudflared tunnel ingress validate
echo "    Validation passed."

# ── 7. Restart cloudflared ───────────────────────────────────────────────────
echo "==> Restarting cloudflared..."
sudo systemctl restart cloudflared
sleep 3
sudo systemctl status cloudflared --no-pager | head -20

# ── 8. Smoke-test all three hostnames ────────────────────────────────────────
echo ""
echo "==> Smoke-testing public endpoints (allow up to 30s for tunnel to re-establish)..."
sleep 10

for HOST in api.theeyebeta.store dataapi.theeyebeta.store admin.theeyebeta.store; do
  HTTP=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 "https://${HOST}" || echo "FAILED")
  if [[ "$HTTP" == "FAILED" ]]; then
    echo "  FAIL  https://${HOST} — curl error"
  elif [[ "$HTTP" -ge 200 && "$HTTP" -lt 500 ]]; then
    echo "  OK    https://${HOST} → HTTP ${HTTP}"
  else
    echo "  WARN  https://${HOST} → HTTP ${HTTP}"
  fi
done

echo ""
echo "Done. If any hostname shows FAIL, check: sudo journalctl -u cloudflared -n 50"
