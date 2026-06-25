"""decision_id traceability through TicketSynthesizer.synthesize()."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS = Path(__file__).resolve().parent
for _p in (_SRC, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from conftest import SNAPSHOT_ID, _agent_result  # noqa: E402

from master_orchestrator.models import TradeTicket  # noqa: E402
from master_orchestrator.synthesis import TicketSynthesizer  # noqa: E402

_ = SNAPSHOT_ID


@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesize_backfills_decision_id_when_llm_omits_it() -> None:
    """The real LLM path never asks for decision_id; synthesize() must stitch it back in."""
    trio = [_agent_result("macro-lead", decision="BUY", instrument_id=7)]
    expected_decision_id = trio[0].decisions[0].decision_id

    llm_ticket = TradeTicket(
        market="US",
        instrument_id=7,
        side="buy",
        qty=100.0,
        horizon_days=10,
        rationale_summary="Synthesized from agent consensus.",
    )
    assert llm_ticket.decision_id is None

    synthesizer = TicketSynthesizer(
        virtual_key="sk-test",
        base_url="http://llm-gateway.test",
        default_qty=100.0,
    )

    with patch.object(
        TicketSynthesizer,
        "_synthesize_llm",
        AsyncMock(return_value=llm_ticket),
    ):
        ticket = await synthesizer.synthesize(
            market="US",
            agent_results=trio,
            transcript=None,
            default_instrument_id=7,
        )

    assert ticket.decision_id == UUID(expected_decision_id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesize_heuristic_path_keeps_its_own_decision_id() -> None:
    """The heuristic fallback already sets decision_id; synthesize() must not clobber it."""
    trio = [_agent_result("macro-lead", decision="BUY", instrument_id=3)]
    expected_decision_id = trio[0].decisions[0].decision_id

    synthesizer = TicketSynthesizer(
        virtual_key="",
        base_url="http://llm-gateway.test",
        default_qty=100.0,
    )

    ticket = await synthesizer.synthesize(
        market="US",
        agent_results=trio,
        transcript=None,
        default_instrument_id=3,
    )

    assert ticket.decision_id == UUID(expected_decision_id)
