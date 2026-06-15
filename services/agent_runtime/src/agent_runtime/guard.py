"""Inline output guard — JSON parse, schema, symbol, creative-content, evidence."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .schemas import AgentOutput

# Maps internal guard kinds to theeyebeta.guard_violations.violation_type CHECK values.
VIOLATION_TYPE_DB: dict[str, str] = {
    "schema_invalid_json": "schema",
    "schema_pydantic": "schema",
    "unknown_symbol": "forbidden_target",
    "creative_content": "creative_content",
    "missing_evidence": "missing_evidence",
}


class GuardViolation(Exception):  # noqa: N818 — established API name; renaming would break callers
    """Raised when agent output fails a guard check."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail

    @property
    def db_violation_type(self) -> str:
        """Return the violation_type value allowed by the DB CHECK constraint."""
        return VIOLATION_TYPE_DB.get(self.kind, "schema")


CREATIVE_PATTERNS = [
    r"\bI suggest\b",
    r"\bI recommend\b",
    r"\ba better approach\b",
    r"\blet me reconsider\b",
    r"\bin my opinion\b",
    r"\bhave you considered\b",
    r"\bperhaps we should\b",
]
CREATIVE_RE = re.compile("|".join(CREATIVE_PATTERNS), re.IGNORECASE)


def validate_output(raw_text: str, valid_symbols: set[str]) -> AgentOutput:
    """Parse and validate raw LLM text against the AgentOutput contract.

    Args:
        raw_text: Raw assistant message (JSON, optionally wrapped in fences).
        valid_symbols: Set of symbols from snapshot.universe.

    Returns:
        Validated :class:`AgentOutput`.

    Raises:
        GuardViolation: On JSON, schema, symbol, creative-content, or evidence failure.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GuardViolation("schema_invalid_json", str(exc)) from exc

    try:
        out = AgentOutput.model_validate(payload)
    except ValidationError as exc:
        raise GuardViolation("schema_pydantic", str(exc)) from exc

    for d in out.decisions:
        if d.instrument_symbol not in valid_symbols:
            raise GuardViolation(
                "unknown_symbol",
                f"{d.instrument_symbol} not in universe {sorted(valid_symbols)}",
            )

    for d in out.decisions:
        if CREATIVE_RE.search(d.rationale):
            raise GuardViolation(
                "creative_content",
                f"{d.instrument_symbol}: rationale contains improvement-language pattern",
            )

    path_re = re.compile(r"\b(?:technicals|prices|macro)\.[A-Za-z0-9_.]+")
    for d in out.decisions:
        combined = d.rationale + " " + " ".join(d.key_drivers)
        if not path_re.search(combined):
            raise GuardViolation(
                "missing_evidence",
                f"{d.instrument_symbol}: no snapshot field path cited",
            )

    return out
