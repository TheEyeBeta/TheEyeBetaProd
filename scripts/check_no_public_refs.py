#!/usr/bin/env python3
"""Fail CI when runtime code references legacy public.* or TheEyeBetaLocal."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN_DIRS = ("workers", "tb")
ALLOWLIST = {
    ROOT / "scripts" / "backfill_prices.py",
    ROOT / "scripts" / "mirror_canonical_prices_to_public.py",
    ROOT / "scripts" / "cleanup_public_orphans.py",
    ROOT / "scripts" / "list_pending_migrations.py",
    ROOT / "scripts" / "diagnose_db_state.py",
}

PATTERNS = (
    re.compile(r"public\.\w+"),
    re.compile(r"TheEyeBetaLocal"),
    re.compile(r"\./theeye\b"),
)


def main() -> int:
    """Scan allowed trees and exit 1 on forbidden references."""
    violations: list[str] = []
    for scan_dir in SCAN_DIRS:
        base = ROOT / scan_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path in ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in PATTERNS:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    violations.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    if violations:
        print("Legacy public/Local references found in runtime paths:", file=sys.stderr)
        for item in violations:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("check_no_public_refs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
