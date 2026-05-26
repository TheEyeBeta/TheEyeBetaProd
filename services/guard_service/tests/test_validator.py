"""Unit tests for ConstitutionGuard validators."""

from __future__ import annotations

import json

import pytest
from zinc_schemas.constitution import AgentConstitution, MandateRules

from guard_service.validator import ConstitutionGuard, Outcome


def valid_output(symbol: str = "AAPL", confidence: float = 0.7) -> str:
    """Build a guard-passing agent output JSON string."""
    payload = {
        "market_stance": "neutral",
        "regime_call": "ranging",
        "decisions": [
            {
                "instrument_symbol": symbol,
                "decision": "HOLD",
                "confidence": confidence,
                "horizon_days": 10,
                "key_drivers": ["macro.us.dgs10 stable", "technicals.AAPL.rsi14 neutral"],
                "rationale": (
                    f"technicals.{symbol}.rsi14 near mid-range; macro.us.dgs10 unchanged."
                ),
            },
        ],
    }
    return json.dumps(payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schema_rejects_invalid_json(guard) -> None:
    """Validator 1 catches non-JSON output."""
    result = await guard.validate(agent_id="macro-lead", raw_output="not json")
    assert result.violations[0].type == "schema"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schema_rejects_unknown_field(guard) -> None:
    """Validator 1 catches extra properties."""
    payload = json.loads(valid_output())
    payload["injected"] = True
    result = await guard.validate(agent_id="macro-lead", raw_output=json.dumps(payload))
    assert result.violations[0].type == "schema"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confidence_range_rejects_out_of_band(guard) -> None:
    """Validator 2 catches confidence outside [0, 1]."""
    result = await guard.validate(agent_id="macro-lead", raw_output=valid_output(confidence=1.2))
    assert result.violations[0].type == "confidence_range"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_evidence_requires_citation(guard, snapshot_us_aapl) -> None:
    """Validator 3 catches numeric claims without snapshot evidence."""
    payload = json.loads(valid_output())
    payload["decisions"][0]["rationale"] = "Target price 150 within 30 days."
    payload["decisions"][0]["key_drivers"] = []
    result = await guard.validate(
        agent_id="macro-lead",
        raw_output=json.dumps(payload),
        snapshot=snapshot_us_aapl,
    )
    assert result.violations[0].type == "missing_evidence"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_whitelist_rejects_unknown_tool(guard) -> None:
    """Validator 4 catches non-whitelisted tool calls."""
    result = await guard.validate(
        agent_id="macro-lead",
        raw_output=valid_output(),
        tool_calls=[{"name": "delete_database", "arguments_json": "{}"}],
    )
    assert result.violations[0].type == "tool_whitelist"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creative_content_rejects_improvement_language(guard) -> None:
    """Validator 5 catches creative/improvement phrasing."""
    payload = json.loads(valid_output())
    payload["decisions"][0]["rationale"] = (
        "I recommend increasing exposure; technicals.AAPL.rsi14 elevated."
    )
    result = await guard.validate(agent_id="macro-lead", raw_output=json.dumps(payload))
    assert result.violations[0].type == "creative_content"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mandate_boundary_rejects_forbidden_suffix() -> None:
    """Validator 6 catches Japanese tickers for Taiwan mandate preset."""
    constitution = AgentConstitution(
        agent_id="taiwan-equity-lead",
        name="Taiwan Lead",
        description="TW mandate",
        model="claude-sonnet-4-6",
        fallback=None,
        max_turns=4,
        output_schema_version=1,
        tools=[],
        forbidden_targets=[],
        mandate=MandateRules(allowed_markets=["TW"], forbidden_symbol_suffixes=[".T"]),
        system_prompt="",
    )
    guard = ConstitutionGuard({"taiwan-equity-lead": constitution})
    result = await guard.validate(
        agent_id="taiwan-equity-lead",
        raw_output=valid_output(symbol="7203.T"),
        snapshot={"market": "TW", "universe": [], "technicals": {}, "prices": {}, "macro": {}},
        valid_symbols={"2330.TW"},
    )
    assert result.violations[0].type == "mandate_boundary"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_forbidden_target_rejects_audit_log_reference() -> None:
    """Validator 7 catches forbidden table/symbol targets for R&D agents."""
    constitution = AgentConstitution(
        agent_id="rnd-agent",
        name="R&D Agent",
        description="Research proposals only",
        model="gpt-5",
        fallback=None,
        max_turns=2,
        output_schema_version=1,
        tools=[],
        forbidden_targets=["audit_log", "proposals"],
        mandate=None,
        system_prompt="",
    )
    guard = ConstitutionGuard({"rnd-agent": constitution})
    payload = json.loads(valid_output())
    payload["decisions"][0]["rationale"] = "Update audit_log retention policy."
    result = await guard.validate(agent_id="rnd-agent", raw_output=json.dumps(payload))
    assert result.violations[0].type == "forbidden_target"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_valid_output_passes(guard, snapshot_us_aapl) -> None:
    """Clean macro-lead output receives PASS."""
    result = await guard.validate(
        agent_id="macro-lead",
        raw_output=valid_output(),
        snapshot=snapshot_us_aapl,
        valid_symbols={"AAPL"},
    )
    assert result.outcome == Outcome.PASS
    assert not result.violations


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolution_policy_retry_escalate_reject(guard) -> None:
    """1st failure RETRY, 2nd ESCALATE, 3rd REJECT."""
    bad = valid_output(confidence=2.0)
    first = await guard.validate(agent_id="macro-lead", raw_output=bad, prior_violation_count=0)
    second = await guard.validate(agent_id="macro-lead", raw_output=bad, prior_violation_count=1)
    third = await guard.validate(agent_id="macro-lead", raw_output=bad, prior_violation_count=2)
    assert first.outcome == Outcome.RETRY
    assert second.outcome == Outcome.ESCALATE
    assert third.outcome == Outcome.REJECT
    assert first.sanitized_output.startswith("STRICT MODE")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hundred_valid_decisions_zero_false_positives(guard, snapshot_us_aapl) -> None:
    """100 synthetic valid decisions all pass (replay sample)."""
    for i in range(100):
        confidence = round(0.5 + (i % 50) / 100.0, 2)
        result = await guard.validate(
            agent_id="macro-lead",
            raw_output=valid_output(confidence=confidence),
            snapshot=snapshot_us_aapl,
            valid_symbols={"AAPL"},
        )
        assert result.outcome == Outcome.PASS, f"false positive at sample {i}"
