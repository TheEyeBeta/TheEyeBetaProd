#!/usr/bin/env bash
# CI staleness guard for docs/api/*.openapi.json
#
# Re-generates each service's OpenAPI schema into a temp directory and diffs
# it against the committed copy.  Exits 1 if anything is stale.
# HTML files are intentionally excluded — they are derived output and are
# checked separately by comparing the source JSON.
#
# Usage (from repo root):
#   bash scripts/check_openapi.sh
#   make docs-api-check

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs/api"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

fail=0

for svc in admin oms; do
    committed="$DOCS_DIR/$svc.openapi.json"

    if [ ! -f "$committed" ]; then
        echo "MISSING: $committed — run: make docs-api"
        fail=1
        continue
    fi

    uv run --no-sync python "$REPO_ROOT/scripts/dump_openapi.py" "$svc" > "$tmpdir/$svc.openapi.json"

    if ! diff -q "$committed" "$tmpdir/$svc.openapi.json" > /dev/null 2>&1; then
        echo "STALE:   $committed — run: make docs-api"
        # Print a unified diff for the CI log so the developer can see what changed.
        diff -u "$committed" "$tmpdir/$svc.openapi.json" || true
        fail=1
    else
        echo "OK:      $committed"
    fi
done

if [ "$fail" -ne 0 ]; then
    echo ""
    echo "One or more OpenAPI schemas are stale."
    echo "Fix: run 'make docs-api' from the repo root, then commit the updated files."
    exit 1
fi

echo ""
echo "All OpenAPI schemas are up-to-date."
