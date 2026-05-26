#!/usr/bin/env bash
# Run Alembic migrations for all services that have a migrations/ directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_migrations() {
    local svc_dir="$1"
    local svc_name
    svc_name="$(basename "$svc_dir")"

    if [[ -f "$svc_dir/alembic.ini" ]]; then
        echo "→ Migrating service: $svc_name"
        (cd "$svc_dir" && uv run alembic upgrade head)
        echo "  ✓ $svc_name migrations complete"
    else
        echo "  ⏭ Skipping $svc_name (no alembic.ini)"
    fi
}

echo "Running database migrations..."
echo ""

if [[ -f "$REPO_ROOT/db/alembic.ini" ]]; then
    echo "→ Migrating central schema (db/)"
    (cd "$REPO_ROOT/db" && uv run alembic upgrade head)
    echo "  ✓ central migrations complete"
fi

echo ""
echo "Running per-service migrations..."
echo ""

for svc_dir in "$REPO_ROOT"/services/*/; do
    run_migrations "$svc_dir"
done

echo ""
echo "All migrations complete."
