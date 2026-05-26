"""Guard-service client for rnd-agent raw JSON validation."""

from __future__ import annotations

import json
from dataclasses import dataclass

import grpc
import structlog

from zinc_proto import guard_pb2, guard_pb2_grpc

log = structlog.get_logger()

_OUTCOME_PASS = guard_pb2.PASS


@dataclass(frozen=True)
class GuardResult:
    """Result of guard validation for rnd output."""

    approved: bool
    outcome: str
    violations: list[dict[str, str]]
    sanitized_output: str


async def validate_rnd_output(
    *,
    grpc_target: str,
    agent_id: str,
    run_id: str,
    raw_output: str,
    tool_calls: list[dict[str, str]] | None = None,
) -> GuardResult:
    """Call ``ValidateAgentOutput`` on guard-service."""
    request = guard_pb2.ValidateRequest(
        agent_id=agent_id,
        run_id=run_id,
        raw_output=raw_output,
    )
    for call in tool_calls or []:
        request.tool_calls.add(
            name=call.get("name", ""),
            arguments_json=call.get("arguments_json", "{}"),
        )
    async with grpc.aio.insecure_channel(grpc_target) as channel:
        stub = guard_pb2_grpc.GuardStub(channel)
        response = await stub.ValidateAgentOutput(request, timeout=60.0)

    outcome_map = {
        guard_pb2.PASS: "PASS",
        guard_pb2.RETRY: "RETRY",
        guard_pb2.ESCALATE: "ESCALATE",
        guard_pb2.REJECT: "REJECT",
    }
    outcome = outcome_map.get(response.outcome, "REJECT")
    violations = [
        {"type": v.type, "severity": v.severity, "detail": v.detail} for v in response.violations
    ]
    return GuardResult(
        approved=outcome == "PASS",
        outcome=outcome,
        violations=violations,
        sanitized_output=response.sanitized_output or raw_output,
    )


def raw_from_chat_content(content: str | dict | list | None) -> str:
    """Normalize LLM chat content to a JSON string."""
    if content is None:
        return "{}"
    if isinstance(content, str):
        return content
    return json.dumps(content)
