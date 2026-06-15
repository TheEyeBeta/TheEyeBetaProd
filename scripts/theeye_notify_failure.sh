#!/usr/bin/env bash
# Alert script invoked by theeye-notify-failure@.service when a theeye unit fails.
# Writes to /var/log/theeye/failures.log and emits a CRITICAL journal entry.
set -euo pipefail

UNIT="${1:-unknown-unit}"
LOG_DIR="/var/log/theeye"
LOG_FILE="$LOG_DIR/failures.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MSG="CRITICAL: $UNIT FAILED at $TS — check: journalctl -u $UNIT"

mkdir -p "$LOG_DIR"
echo "[$TS] $MSG" >> "$LOG_FILE"

# Emit a CRITICAL-priority entry visible in journalctl -p crit -t theeye-alert
echo "$MSG" | systemd-cat -p crit -t theeye-alert
