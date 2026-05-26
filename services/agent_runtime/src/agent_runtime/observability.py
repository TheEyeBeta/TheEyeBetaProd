"""Prometheus metrics for agent-runtime runs."""

from __future__ import annotations

from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram

agent_runs_total = Counter(
    "agent_runs_total",
    "Agent runs by terminal status",
    labelnames=("agent_id", "status"),
)

agent_run_duration_seconds = Histogram(
    "agent_run_duration_seconds",
    "Wall-clock duration of a full agent run",
    labelnames=("agent_id",),
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

agent_tokens_total = Counter(
    "agent_tokens_total",
    "LLM tokens consumed per agent run",
    labelnames=("agent_id", "kind"),
)

agent_last_success_timestamp = Gauge(
    "agent_last_success_timestamp",
    "Unix timestamp of the last successful agent run",
    labelnames=("agent_id",),
)


def record_run_success(
    agent_id: str,
    *,
    duration_seconds: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record a successful agent run."""
    agent_runs_total.labels(agent_id=agent_id, status="succeeded").inc()
    agent_run_duration_seconds.labels(agent_id=agent_id).observe(duration_seconds)
    if input_tokens > 0:
        agent_tokens_total.labels(agent_id=agent_id, kind="input").inc(input_tokens)
    if output_tokens > 0:
        agent_tokens_total.labels(agent_id=agent_id, kind="output").inc(output_tokens)
    agent_last_success_timestamp.labels(agent_id=agent_id).set(
        datetime.now(tz=UTC).timestamp(),
    )


def record_run_failure(agent_id: str, *, duration_seconds: float) -> None:
    """Record a failed agent run."""
    agent_runs_total.labels(agent_id=agent_id, status="failed").inc()
    agent_run_duration_seconds.labels(agent_id=agent_id).observe(duration_seconds)
