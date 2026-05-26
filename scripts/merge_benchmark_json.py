#!/usr/bin/env python3
"""Merge per-module Google Benchmark JSON files into one baseline artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def merge(inputs: list[Path]) -> dict[str, object]:
    benchmarks: list[dict[str, object]] = []
    context: dict[str, object] = {}
    for path in inputs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not context and "context" in payload:
            context = payload["context"]
        benchmarks.extend(payload.get("benchmarks", []))
    return {"context": context, "benchmarks": benchmarks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Merged JSON output path")
    parser.add_argument("inputs", type=Path, nargs="+", help="Benchmark JSON inputs")
    args = parser.parse_args()

    merged = merge(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(merged['benchmarks'])} benchmarks to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
