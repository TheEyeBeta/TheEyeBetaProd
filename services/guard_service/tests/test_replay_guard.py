"""Replay historical agent outputs through guard; assert PASS and decision parity."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_FIXTURES = Path(__file__).parent / "fixtures" / "replay_outputs.json"


@pytest.fixture
def replay_cases() -> list[dict]:
    """Historical outputs with expected agent_decisions fields."""
    return json.loads(_FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_outputs_pass_and_match_decisions(replay_cases: list[dict]) -> None:
    """Guard PASS on replay fixtures; parsed decisions match expected rows."""
    from guard_service.app import build_guard, validate_request  # noqa: PLC0415
    from guard_service.validator import Outcome  # noqa: PLC0415
    from zinc_proto import guard_pb2  # noqa: PLC0415

    with (
        patch.dict("os.environ", {"GUARD_DISABLE_CREATIVE_CLASSIFIER": "1"}, clear=False),
        patch("guard_service.app.count_violations_for_run", AsyncMock(return_value=0)),
        patch("guard_service.app.insert_violations", AsyncMock()),
    ):
        guard = build_guard()
        for case in replay_cases:
            request = guard_pb2.ValidateRequest(
                agent_id=case["agent_id"],
                run_id="00000000-0000-0000-0000-000000000001",
                raw_output=case["raw_output"],
                snapshot_json=json.dumps(case["snapshot"]),
                valid_symbols=case["valid_symbols"],
            )
            result = await validate_request(guard, request)
            assert result.outcome == Outcome.PASS, case["agent_id"]
            assert result.parsed is not None
            decisions = result.parsed.get("decisions") or []
            assert len(decisions) == len(case["expected_decisions"])
            for got, expected in zip(decisions, case["expected_decisions"], strict=True):
                assert got["instrument_symbol"] == expected["instrument_symbol"]
                assert got["decision"] == expected["decision"]
                assert float(got["confidence"]) == pytest.approx(expected["confidence"])
                assert int(got["horizon_days"]) == expected["horizon_days"]
