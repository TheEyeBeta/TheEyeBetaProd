"""ConstitutionGuard — ordered validators for agent LLM output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol

import structlog

from zinc_schemas.constitution import AgentConstitution, MandateRules

log = structlog.get_logger()

STRICT_MODE_PREFIX = (
    "STRICT MODE: Your prior output violated the constitution. "
    "Return ONLY valid JSON matching the output schema. "
    "Every numeric claim must cite snapshot evidence_refs or field paths. "
    "Do not use improvement language.\n\n"
)

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
SNAPSHOT_PATH_RE = re.compile(r"^(technicals|prices|macro)\.[A-Za-z0-9_.]+$")
SNAPSHOT_PATH_IN_TEXT_RE = re.compile(r"\b(?:technicals|prices|macro)\.[A-Za-z0-9_.]+")
NUMERIC_CLAIM_RE = re.compile(
    r"\b\d+(?:\.\d+)?%?\b|\b(?:above|below|at)\s+\d+(?:\.\d+)?",
    re.IGNORECASE,
)
FORBIDDEN_TARGET_DEFAULTS: dict[str, list[str]] = {
    "rnd-agent": ["audit_log", "proposals", "guard_violations", "mandate"],
}

# Taiwan lead example: cannot propose Japanese-listed tickers (suffix .T).
MANDATE_PRESETS: dict[str, MandateRules] = {
    "taiwan-equity-lead": MandateRules(
        allowed_markets=["TW"],
        forbidden_symbol_suffixes=[".T"],
        forbidden_exchanges=["XTKS"],
    ),
}


class Outcome(IntEnum):
    """Validation outcome returned to callers."""

    PASS = 0
    RETRY = 1
    ESCALATE = 2
    REJECT = 3


@dataclass(frozen=True)
class Violation:
    """Single guard violation."""

    type: str
    severity: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        """Serialize for HTTP/JSON consumers."""
        return {"type": self.type, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class ValidationResult:
    """Result of :meth:`ConstitutionGuard.validate`."""

    outcome: Outcome
    violations: list[Violation]
    sanitized_output: str
    parsed: dict[str, Any] | None = None


class CreativeClassifier(Protocol):
    """Optional Haiku classifier for creative-content (P-GS-02)."""

    async def classify(self, text: str, *, agent_id: str) -> float:
        """Return probability in [0, 1] that text is creative/improvement language."""


class ConstitutionGuard:
    """Stateless guard applying constitution rules in fixed order."""

    def __init__(
        self,
        constitutions: dict[str, AgentConstitution],
        *,
        creative_classifier: CreativeClassifier | None = None,
        creative_threshold: float = 0.6,
    ) -> None:
        """Initialize with pre-loaded constitutions keyed by agent_id."""
        self._constitutions = constitutions
        self._creative_classifier = creative_classifier
        self._creative_threshold = creative_threshold

    def get_constitution(self, agent_id: str) -> AgentConstitution:
        """Return the constitution for an agent or raise."""
        if agent_id not in self._constitutions:
            msg = f"Unknown agent_id: {agent_id}"
            raise KeyError(msg)
        return self._constitutions[agent_id]

    async def validate(
        self,
        *,
        agent_id: str,
        raw_output: str,
        tool_calls: list[dict[str, str]] | None = None,
        valid_symbols: set[str] | None = None,
        snapshot: dict[str, Any] | None = None,
        prior_violation_count: int = 0,
    ) -> ValidationResult:
        """Run validators in order; map violation count to Outcome.

        Args:
            agent_id: Agent identifier.
            raw_output: Raw LLM JSON text (optional markdown fences).
            tool_calls: OpenAI-style tool call dicts with ``name`` keys.
            valid_symbols: Universe symbols from packaged snapshot.
            snapshot: Packaged snapshot dict for evidence/mandate checks.
            prior_violation_count: Existing ``guard_violations`` rows for this run.

        Returns:
            :class:`ValidationResult` with outcome and violation list.
        """
        constitution = self.get_constitution(agent_id)
        text = _strip_fences(raw_output)
        violations: list[Violation] = []
        parsed: dict[str, Any] | None = None

        checks: list[tuple[str, Any]] = [
            ("schema", self._check_schema(constitution, text)),
        ]
        if constitution.output_schema_version == 1:
            checks.extend(
                [
                    ("confidence_range", self._check_confidence_range(text)),
                    ("missing_evidence", self._check_missing_evidence(text, snapshot)),
                    (
                        "mandate_boundary",
                        self._check_mandate_boundary(
                            agent_id,
                            constitution,
                            text,
                            snapshot,
                            valid_symbols,
                        ),
                    ),
                ],
            )
        else:
            checks.append(
                ("proposal_impact", self._check_proposal_impact_confidence(text)),
            )
        checks.extend(
            [
                ("tool_whitelist", self._check_tool_whitelist(constitution, tool_calls or [])),
                ("creative_content", await self._check_creative_content(agent_id, text)),
                ("forbidden_target", self._check_forbidden_target(agent_id, constitution, text)),
            ],
        )
        for _name, hit in checks:
            if hit:
                violations.extend(hit)
                break

        if not violations:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return ValidationResult(
                outcome=Outcome.PASS,
                violations=[],
                sanitized_output=text,
                parsed=parsed,
            )

        attempt = prior_violation_count + 1
        if attempt >= 3:
            outcome = Outcome.REJECT
        elif attempt == 2:
            outcome = Outcome.ESCALATE
        else:
            outcome = Outcome.RETRY

        sanitized = text
        if outcome == Outcome.RETRY:
            sanitized = STRICT_MODE_PREFIX + text

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

        return ValidationResult(
            outcome=outcome,
            violations=violations,
            sanitized_output=sanitized,
            parsed=parsed,
        )

    def _check_schema(
        self,
        constitution: AgentConstitution,
        text: str,
    ) -> list[Violation] | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return [
                Violation(type="schema", severity="high", detail=str(exc)),
            ]
        validator = constitution.output_validator()
        errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            detail = "; ".join(e.message for e in errors[:5])
            return [Violation(type="schema", severity="high", detail=detail)]
        return None

    def _check_proposal_impact_confidence(self, text: str) -> list[Violation] | None:
        """Validate ``estimated_impact.confidence`` for rnd proposal output (schema v2)."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        hits: list[Violation] = []
        for idx, proposal in enumerate(payload.get("proposals") or []):
            if not isinstance(proposal, dict):
                continue
            impact = proposal.get("estimated_impact")
            if not isinstance(impact, dict):
                continue
            conf = impact.get("confidence")
            if conf is None:
                continue
            try:
                value = float(conf)
            except (TypeError, ValueError):
                hits.append(
                    Violation(
                        type="confidence_range",
                        severity="medium",
                        detail=f"proposal[{idx}]: estimated_impact.confidence not numeric",
                    ),
                )
                continue
            if not 0.0 <= value <= 1.0:
                hits.append(
                    Violation(
                        type="confidence_range",
                        severity="medium",
                        detail=f"proposal[{idx}]: confidence {value} outside [0, 1]",
                    ),
                )
        return hits or None

    def _check_confidence_range(self, text: str) -> list[Violation] | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        hits: list[Violation] = []
        for decision in payload.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            conf = decision.get("confidence")
            if conf is None:
                continue
            try:
                value = float(conf)
            except (TypeError, ValueError):
                hits.append(
                    Violation(
                        type="confidence_range",
                        severity="medium",
                        detail=f"{decision.get('instrument_symbol')}: confidence not numeric",
                    ),
                )
                continue
            if not 0.0 <= value <= 1.0:
                hits.append(
                    Violation(
                        type="confidence_range",
                        severity="medium",
                        detail=(
                            f"{decision.get('instrument_symbol')}: "
                            f"confidence {value} outside [0, 1]"
                        ),
                    ),
                )
        return hits or None

    def _check_missing_evidence(
        self,
        text: str,
        snapshot: dict[str, Any] | None,
    ) -> list[Violation] | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        hits: list[Violation] = []
        snapshot_paths = _snapshot_field_paths(snapshot) if snapshot else set()

        for decision in payload.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            symbol = str(decision.get("instrument_symbol", "?"))
            refs = decision.get("evidence_refs") or []
            rationale = str(decision.get("rationale", ""))
            drivers = " ".join(str(d) for d in (decision.get("key_drivers") or []))
            combined = f"{rationale} {drivers}"

            valid_refs = [r for r in refs if isinstance(r, str) and SNAPSHOT_PATH_RE.match(r)]
            if refs and not valid_refs:
                hits.append(
                    Violation(
                        type="missing_evidence",
                        severity="medium",
                        detail=f"{symbol}: evidence_refs must be snapshot field paths",
                    ),
                )
                continue

            if valid_refs and snapshot_paths:
                missing = [r for r in valid_refs if r not in snapshot_paths]
                if missing:
                    hits.append(
                        Violation(
                            type="missing_evidence",
                            severity="medium",
                            detail=f"{symbol}: unknown evidence_refs {missing}",
                        ),
                    )
                    continue

            has_path_citation = bool(SNAPSHOT_PATH_IN_TEXT_RE.search(combined))
            if valid_refs or has_path_citation:
                continue

            if NUMERIC_CLAIM_RE.search(combined):
                hits.append(
                    Violation(
                        type="missing_evidence",
                        severity="medium",
                        detail=(
                            f"{symbol}: numeric claim without evidence_refs "
                            "or snapshot path citation"
                        ),
                    ),
                )
        return hits or None

    def _check_tool_whitelist(
        self,
        constitution: AgentConstitution,
        tool_calls: list[dict[str, str]],
    ) -> list[Violation] | None:
        allowed = set(constitution.tools)
        if not tool_calls:
            return None
        hits: list[Violation] = []
        for call in tool_calls:
            name = str(call.get("name", ""))
            if name and name not in allowed:
                hits.append(
                    Violation(
                        type="tool_whitelist",
                        severity="high",
                        detail=f"tool {name!r} not in constitution.tools {sorted(allowed)}",
                    ),
                )
        return hits or None

    async def _check_creative_content(
        self,
        agent_id: str,
        text: str,
    ) -> list[Violation] | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            if CREATIVE_RE.search(text):
                return [
                    Violation(
                        type="creative_content",
                        severity="medium",
                        detail="raw output contains improvement-language pattern",
                    ),
                ]
            return None

        hits: list[Violation] = []
        for decision in payload.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            symbol = str(decision.get("instrument_symbol", "?"))
            rationale = str(decision.get("rationale", ""))
            if CREATIVE_RE.search(rationale):
                hits.append(
                    Violation(
                        type="creative_content",
                        severity="medium",
                        detail=f"{symbol}: rationale contains improvement-language pattern",
                    ),
                )
                continue
            if self._creative_classifier is not None and rationale.strip():
                score = await self._creative_classifier.classify(
                    rationale,
                    agent_id=agent_id,
                )
                if score >= self._creative_threshold:
                    hits.append(
                        Violation(
                            type="creative_content",
                            severity="medium",
                            detail=(
                                f"{symbol}: classifier score {score:.2f} "
                                f">= {self._creative_threshold}"
                            ),
                        ),
                    )
        return hits or None

    def _check_mandate_boundary(
        self,
        agent_id: str,
        constitution: AgentConstitution,
        text: str,
        snapshot: dict[str, Any] | None,
        valid_symbols: set[str] | None,
    ) -> list[Violation] | None:
        rules = constitution.mandate or MANDATE_PRESETS.get(agent_id)
        if rules is None:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None

        market = str((snapshot or {}).get("market", ""))
        if rules.allowed_markets and market and market not in rules.allowed_markets:
            return [
                Violation(
                    type="mandate_boundary",
                    severity="high",
                    detail=f"market {market!r} not in allowed {rules.allowed_markets}",
                ),
            ]

        hits: list[Violation] = []
        for decision in payload.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            symbol = str(decision.get("instrument_symbol", ""))
            for suffix in rules.forbidden_symbol_suffixes:
                if symbol.endswith(suffix):
                    hits.append(
                        Violation(
                            type="mandate_boundary",
                            severity="high",
                            detail=f"{symbol}: forbidden suffix {suffix!r} for {agent_id}",
                        ),
                    )
            if valid_symbols is not None and symbol and symbol not in valid_symbols:
                if rules.allowed_markets:
                    hits.append(
                        Violation(
                            type="mandate_boundary",
                            severity="high",
                            detail=f"{symbol}: not in snapshot universe for mandate",
                        ),
                    )
        return hits or None

    def _check_forbidden_target(
        self,
        agent_id: str,
        constitution: AgentConstitution,
        text: str,
    ) -> list[Violation] | None:
        forbidden = set(constitution.forbidden_targets or FORBIDDEN_TARGET_DEFAULTS.get(agent_id, []))
        if not forbidden:
            return None
        lowered = text.lower()
        hits: list[Violation] = []
        for target in forbidden:
            if target.lower() in lowered:
                hits.append(
                    Violation(
                        type="forbidden_target",
                        severity="critical",
                        detail=f"output references forbidden target {target!r}",
                    ),
                )
        return hits or None


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _snapshot_field_paths(snapshot: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for symbol, block in (snapshot.get("technicals") or {}).items():
        if isinstance(block, dict):
            for key in block:
                paths.add(f"technicals.{symbol}.{key}")
    for symbol, block in (snapshot.get("prices") or {}).items():
        if isinstance(block, dict):
            for key in block:
                paths.add(f"prices.{symbol}.{key}")
    for key in (snapshot.get("macro") or {}):
        paths.add(f"macro.{key}")
    return paths

