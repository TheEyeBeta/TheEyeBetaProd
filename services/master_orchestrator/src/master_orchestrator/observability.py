"""Prometheus metrics for master-orchestrator market trios."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Counter, Histogram

TrioOutcome = Literal["consensus", "debate", "no-decision", "skipped"]

trios_total = Counter(
    "trios_total",
    "Market trio workflows by terminal outcome",
    labelnames=("market", "outcome"),
)

trio_duration_seconds = Histogram(
    "trio_duration_seconds",
    "Wall-clock duration of a market trio workflow",
    labelnames=("market",),
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

debate_rounds_total = Counter(
    "debate_rounds_total",
    "Debate rebuttal rounds executed",
    labelnames=("market", "round"),
)


def record_trio_outcome(market: str, outcome: TrioOutcome) -> None:
    """Increment trios_total for a terminal workflow outcome."""
    trios_total.labels(market=market.upper(), outcome=outcome).inc()


def record_trio_duration(market: str, duration_seconds: float) -> None:
    """Observe trio_duration_seconds for a completed workflow."""
    trio_duration_seconds.labels(market=market.upper()).observe(duration_seconds)


def record_debate_round(market: str, round_num: int) -> None:
    """Increment debate_rounds_total for one rebuttal round."""
    debate_rounds_total.labels(market=market.upper(), round=str(round_num)).inc()


@contextmanager
def observe_trio_duration(market: str) -> Iterator[None]:
    """Context manager that records trio_duration_seconds on exit."""
    started = time.perf_counter()
    try:
        yield
    finally:
        record_trio_duration(market, time.perf_counter() - started)
