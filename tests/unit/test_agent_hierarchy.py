"""Unit tests for agent chain-of-command hierarchy."""

from __future__ import annotations

from zinc_schemas.agent_hierarchy import load_agent_hierarchy


def test_hierarchy_loads() -> None:
    """Hierarchy YAML parses and includes master-orchestrator."""
    hierarchy = load_agent_hierarchy()
    assert "master-orchestrator" in hierarchy.agents
    assert hierarchy.agents["macro-lead"].reports_to == "markets-lead"
    assert hierarchy.agents["markets-lead"].reports_to == "master-orchestrator"


def test_rollup_order_leaves_before_heads() -> None:
    """Leaves execute before department leads and master-orchestrator."""
    hierarchy = load_agent_hierarchy()
    order = hierarchy.rollup_order()
    assert order.index("macro-lead") < order.index("markets-lead")
    assert order.index("markets-lead") < order.index("master-orchestrator")
    assert order[-1] == "master-orchestrator"


def test_audience_for_operator_facing_head() -> None:
    """Master-orchestrator briefings are addressed to the operator."""
    hierarchy = load_agent_hierarchy()
    assert hierarchy.audience_for("master-orchestrator") == "operator"
    assert hierarchy.audience_for("macro-lead") == "markets-lead"
