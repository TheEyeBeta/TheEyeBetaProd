#!/usr/bin/env python3
"""Compare Google Benchmark JSON output against a baseline (fail on regression)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_benchmarks(path: Path) -> dict[str, float]:
    """Load benchmark name -> real_time (ns) from a JSON file or directory."""
    if path.is_dir():
        merged: dict[str, float] = {}
        for json_path in sorted(path.glob("*.json")):
            merged.update(load_benchmarks(json_path))
        return merged

    payload = json.loads(path.read_text(encoding="utf-8"))
    timings: dict[str, float] = {}
    for entry in payload.get("benchmarks", []):
        name = str(entry.get("name", ""))
        if not name:
            continue
        run_type = entry.get("run_type")
        if run_type == "aggregate" and not name.endswith("_median"):
            continue
        if run_type not in (None, "iteration", "aggregate"):
            continue
        real_time = entry.get("real_time")
        if real_time is None:
            continue
        timings[name] = float(real_time)
    return timings


def compare(
    baseline: dict[str, float],
    current: dict[str, float],
    threshold: float,
) -> list[str]:
    """Return human-readable regression messages."""
    regressions: list[str] = []
    for name, base_time in baseline.items():
        if name not in current:
            regressions.append(f"missing benchmark in current results: {name}")
            continue
        current_time = current[name]
        if base_time <= 0.0:
            continue
        ratio = current_time / base_time
        if ratio > threshold:
            percent = (ratio - 1.0) * 100.0
            regressions.append(
                f"{name}: {current_time:.0f} ns vs baseline {base_time:.0f} ns "
                f"(+{percent:.1f}% > {(threshold - 1.0) * 100:.0f}% limit)"
            )
    return regressions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="Baseline JSON file or directory")
    parser.add_argument("current", type=Path, help="Current JSON file or directory")
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.10,
        help="Fail when current/baseline real_time exceeds this ratio (default: 1.10)",
    )
    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"No baseline at {args.baseline} — skipping regression gate", file=sys.stderr)
        return 0

    baseline = load_benchmarks(args.baseline)
    if not baseline:
        print(f"Baseline {args.baseline} has no benchmarks — skipping regression gate")
        return 0

    if not args.current.exists():
        print(f"Current results missing: {args.current}", file=sys.stderr)
        return 1

    current = load_benchmarks(args.current)
    if not current:
        print(f"Current results at {args.current} have no benchmarks", file=sys.stderr)
        return 1

    regressions = compare(baseline, current, args.threshold)
    if regressions:
        print("Benchmark regressions detected:", file=sys.stderr)
        for message in regressions:
            print(f"  - {message}", file=sys.stderr)
        return 1

    print(f"All {len(baseline)} benchmarks within {(args.threshold - 1.0) * 100:.0f}% threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
