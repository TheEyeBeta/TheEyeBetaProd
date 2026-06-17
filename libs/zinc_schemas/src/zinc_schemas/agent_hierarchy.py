"""Load and validate the agent chain-of-command hierarchy."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

OPERATOR_AUDIENCE = "operator"


def _resolve_hierarchy_path(path: str | None = None) -> Path:
    """Locate ``config/agents/hierarchy.yaml`` from env or repo walk."""
    if path:
        return Path(path)
    env_path = os.environ.get("AGENT_HIERARCHY_PATH")
    if env_path:
        return Path(env_path)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "agents" / "hierarchy.yaml"
        if candidate.is_file():
            return candidate
    msg = "config/agents/hierarchy.yaml not found"
    raise FileNotFoundError(msg)


class AgentHierarchyEntry(BaseModel):
    """One node in the reporting chain."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    reports_to: str | None = None
    department: str | None = None
    role: str | None = None
    constitution_path: str | None = None
    model_default: str | None = None
    model_fallback: str | None = None


class AgentHierarchy(BaseModel):
    """Full chain-of-command graph."""

    model_config = ConfigDict(extra="forbid")

    agents: dict[str, AgentHierarchyEntry]

    def children_of(self, parent_id: str | None) -> list[str]:
        """Return direct reports for a parent (``None`` = operator's direct reports)."""
        if parent_id is None:
            return [aid for aid, entry in self.agents.items() if entry.reports_to is None]
        return [aid for aid, entry in self.agents.items() if entry.reports_to == parent_id]

    def leaves(self) -> list[str]:
        """Agents with no subordinates in the hierarchy."""
        parents = {entry.reports_to for entry in self.agents.values() if entry.reports_to}
        return [aid for aid in self.agents if aid not in parents]

    def rollup_order(self) -> list[str]:
        """Bottom-up execution order: leaves first, operator-facing heads last."""
        order: list[str] = []
        visited: set[str] = set()

        def visit(agent_id: str) -> None:
            if agent_id in visited:
                return
            for child in self.children_of(agent_id):
                visit(child)
            if agent_id in self.agents:
                order.append(agent_id)
            visited.add(agent_id)

        for root in self.children_of(None):
            visit(root)
        return order

    def audience_for(self, agent_id: str) -> str:
        """Who receives this agent's report (parent or operator)."""
        parent = self.agents[agent_id].reports_to
        return parent if parent is not None else OPERATOR_AUDIENCE


def _parse_hierarchy(raw: dict[str, Any]) -> AgentHierarchy:
    agents_raw = raw.get("agents") or {}
    agents: dict[str, AgentHierarchyEntry] = {}
    for agent_id, spec in agents_raw.items():
        if not isinstance(spec, dict):
            spec = {}
        reports_to = spec.get("reports_to")
        agents[agent_id] = AgentHierarchyEntry(
            agent_id=agent_id,
            reports_to=reports_to,
            department=spec.get("department"),
            role=spec.get("role"),
            constitution_path=spec.get("constitution_path"),
            model_default=spec.get("model_default"),
            model_fallback=spec.get("model_fallback"),
        )
    return AgentHierarchy(agents=agents)


@lru_cache
def load_agent_hierarchy(path: str | None = None) -> AgentHierarchy:
    """Load ``config/agents/hierarchy.yaml`` (cached)."""
    hierarchy_path = _resolve_hierarchy_path(path)
    with hierarchy_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return _parse_hierarchy(raw)
