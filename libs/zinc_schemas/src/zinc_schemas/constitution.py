"""Load agent constitution markdown files (YAML frontmatter + body)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
from jsonschema import Draft202012Validator

_SCHEMA_DIR = Path(__file__).resolve().parent
_AGENT_OUTPUT_SCHEMA_V1 = _SCHEMA_DIR / "agent_output_schema_v1.json"
_AGENT_OUTPUT_SCHEMA_V2 = _SCHEMA_DIR / "agent_output_schema_v2.json"


@dataclass
class MandateRules:
    """Per-agent mandate boundaries from constitution frontmatter."""

    allowed_markets: list[str] = field(default_factory=list)
    forbidden_symbol_suffixes: list[str] = field(default_factory=list)
    forbidden_exchanges: list[str] = field(default_factory=list)


@dataclass
class AgentConstitution:
    """Parsed agent constitution from a markdown file.

    Attributes:
        agent_id: Unique agent identifier.
        name: Human-readable agent name.
        description: Short description of the agent's role.
        model: Default LLM model identifier.
        fallback: Optional fallback model, or None.
        max_turns: Maximum conversation turns allowed.
        output_schema_version: Integer version of the output JSON schema.
        tools: Whitelisted tool names the LLM may invoke.
        forbidden_targets: Symbols/table names this agent must not target.
        mandate: Optional geographic/instrument mandate rules.
        system_prompt: Full markdown body fed to the LLM as the system message.
    """

    agent_id: str
    name: str
    description: str
    model: str
    fallback: str | None
    max_turns: int
    output_schema_version: int
    tools: list[str]
    forbidden_targets: list[str]
    mandate: MandateRules | None
    system_prompt: str

    @property
    def output_schema(self) -> dict[str, Any]:
        """Return the JSON Schema dict for this constitution's output version."""
        if self.output_schema_version == 1:
            return json.loads(_AGENT_OUTPUT_SCHEMA_V1.read_text(encoding="utf-8"))
        if self.output_schema_version == 2:
            return json.loads(_AGENT_OUTPUT_SCHEMA_V2.read_text(encoding="utf-8"))
        msg = f"Unsupported output_schema_version: {self.output_schema_version}"
        raise ValueError(msg)

    def output_validator(self) -> Draft202012Validator:
        """Build a jsonschema validator for agent output."""
        return Draft202012Validator(self.output_schema)


def _parse_mandate(raw: object) -> MandateRules | None:
    if not raw or not isinstance(raw, dict):
        return None
    return MandateRules(
        allowed_markets=[str(m) for m in raw.get("allowed_markets") or []],
        forbidden_symbol_suffixes=[
            str(s) for s in raw.get("forbidden_symbol_suffixes") or []
        ],
        forbidden_exchanges=[str(e) for e in raw.get("forbidden_exchanges") or []],
    )


def load_constitution(path: Path) -> AgentConstitution:
    """Parse a constitution markdown file into an :class:`AgentConstitution`.

    Args:
        path: Path to the ``.md`` file (relative paths resolved from cwd).

    Returns:
        Parsed constitution with frontmatter metadata and body as system_prompt.

    Raises:
        ValueError: If required frontmatter keys are missing.
    """
    doc = frontmatter.load(path)
    fm = doc.metadata
    required = {
        "agent_id",
        "name",
        "description",
        "model",
        "max_turns",
        "output_schema_version",
    }
    missing = required - set(fm.keys())
    if missing:
        raise ValueError(f"Constitution {path} missing required frontmatter: {missing}")
    raw_tools = fm.get("tools") or []
    if isinstance(raw_tools, str):
        tools = [raw_tools]
    else:
        tools = [str(t) for t in raw_tools]
    raw_forbidden = fm.get("forbidden_targets") or []
    if isinstance(raw_forbidden, str):
        forbidden_targets = [raw_forbidden]
    else:
        forbidden_targets = [str(t) for t in raw_forbidden]
    return AgentConstitution(
        agent_id=fm["agent_id"],
        name=fm["name"],
        description=fm["description"],
        model=fm["model"],
        fallback=fm.get("fallback"),
        max_turns=int(fm["max_turns"]),
        output_schema_version=int(fm["output_schema_version"]),
        tools=tools,
        forbidden_targets=forbidden_targets,
        mandate=_parse_mandate(fm.get("mandate")),
        system_prompt=doc.content.strip(),
    )


def load_all_constitutions(agents_dir: Path) -> dict[str, AgentConstitution]:
    """Load every ``*.md`` / ``*.agent.md`` constitution under ``agents_dir`` keyed by agent_id."""
    constitutions: dict[str, AgentConstitution] = {}
    paths = sorted(
        p
        for pattern in ("*.md", "*.agent.md")
        for p in agents_dir.rglob(pattern)
        if not p.name.startswith("_")
    )
    for path in paths:
        constitution = load_constitution(path)
        constitutions[constitution.agent_id] = constitution
    return constitutions


def resolve_agents_dir(repo_root: Path | None = None) -> Path:
    """Return the canonical ``agents/`` directory at the repository root."""
    root = repo_root or Path(__file__).resolve().parents[4]
    return root / "agents"
