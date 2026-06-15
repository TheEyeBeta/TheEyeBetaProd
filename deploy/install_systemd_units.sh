#!/usr/bin/env bash
# Install/refresh theeye-* systemd units from the repo (idempotent).
# Usage: sudo deploy/install_systemd_units.sh
set -euo pipefail

REPO_UNITS="$(cd "$(dirname "${BASH_SOURCE[0]}")/systemd" && pwd)"
TARGET=/etc/systemd/system

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi

changed=0
for unit in "$REPO_UNITS"/*.service "$REPO_UNITS"/*.timer; do
    name="$(basename "$unit")"
    if ! cmp -s "$unit" "$TARGET/$name" 2>/dev/null; then
        install -m 0644 "$unit" "$TARGET/$name"
        echo "installed: $name"
        changed=1
    fi
done

if [[ $changed -eq 1 ]]; then
    systemctl daemon-reload
    echo "daemon-reload done"
else
    echo "all units already current"
fi

systemctl list-timers 'theeye-*' --no-pager
