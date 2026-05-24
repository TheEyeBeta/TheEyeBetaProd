"""Load agent constitution markdown files (YAML frontmatter + body)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frontmatter


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
        system_prompt: Full markdown body fed to the LLM as the system message.
    """

    agent_id: str
    name: str
    description: str
    model: str
    fallback: str | None
    max_turns: int
    output_schema_version: int
    system_prompt: str


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
    return AgentConstitution(
        agent_id=fm["agent_id"],
        name=fm["name"],
        description=fm["description"],
        model=fm["model"],
        fallback=fm.get("fallback"),
        max_turns=int(fm["max_turns"]),
        output_schema_version=int(fm["output_schema_version"]),
        system_prompt=doc.content.strip(),
    )
