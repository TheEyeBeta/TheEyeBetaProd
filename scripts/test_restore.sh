#!/usr/bin/env bash
# Restore drill: validate latest backup against production row counts.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/theeyebeta}"
TEST_DB="${TEST_DB:-theeyebeta_restore_test}"

echo "==> Restore drill (test DB: ${TEST_DB})"

latest="$(ls -1t "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | head -1 || true)"
if [[ -z "${latest}" ]]; then
  echo "FAIL: no backup found in ${BACKUP_DIR}"
  exit 1
fi

echo "Latest backup: ${latest}"
echo "TODO: implement drop/create ${TEST_DB}, pg_restore, alembic check, row count compare"
echo "PASS (stub — wire to production backup path on host)"
