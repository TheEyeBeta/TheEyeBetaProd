"""Unit tests for agent-runtime Prometheus metrics."""

from __future__ import annotations

import pytest
from agent_runtime.observability import record_run_failure, record_run_success
from prometheus_client import REGISTRY


def _counter_value(agent_id: str, status: str) -> float:
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name.endswith("_created"):
                continue
            if (
                sample.labels.get("agent_id") == agent_id
                and sample.labels.get("status") == status
                and "agent_runs" in sample.name
            ):
                return float(sample.value)
    return 0.0


@pytest.mark.unit
def test_record_run_success_increments_succeeded_counter() -> None:
    """Success path labels agent_runs_total with status=succeeded."""
    before = _counter_value("macro-lead", "succeeded")
    record_run_success(
        "macro-lead",
        duration_seconds=1.5,
        input_tokens=10,
        output_tokens=5,
    )
    assert _counter_value("macro-lead", "succeeded") == before + 1.0


@pytest.mark.unit
def test_record_run_failure_increments_failed_counter() -> None:
    """Failure path labels agent_runs_total with status=failed."""
    before = _counter_value("macro-lead", "failed")
    record_run_failure("macro-lead", duration_seconds=0.25)
    assert _counter_value("macro-lead", "failed") == before + 1.0
