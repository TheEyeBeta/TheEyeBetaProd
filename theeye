#!/usr/bin/env bash
# Unified operator CLI: Prod ``tb`` with Local ``./theeye`` command surface.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  PROD_ROOT="$SCRIPT_DIR"
else
  PROD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

cd "$PROD_ROOT"
exec uv run --package tb tb "$@"
