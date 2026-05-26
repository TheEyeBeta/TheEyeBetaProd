"""Guard validation — gRPC/HTTP to guard-service with inline fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import grpc
import httpx
import structlog
from zinc_proto import guard_pb2, guard_pb2_grpc

from .guard import GuardViolation, validate_output
from .schemas import AgentOutput

log = structlog.get_logger()

_OUTCOME_PASS = "PASS"
_OUTCOME_RETRY = "RETRY"
_OUTCOME_ESCALATE = "ESCALATE"
_OUTCOME_REJECT = "REJECT"

_PROTO_OUTCOME_TO_STR = {
    guard_pb2.PASS: _OUTCOME_PASS,
    guard_pb2.RETRY: _OUTCOME_RETRY,
    guard_pb2.ESCALATE: _OUTCOME_ESCALATE,
    guard_pb2.REJECT: _OUTCOME_REJECT,
}


class GuardRejectedError(Exception):
    """Raised when guard-service returns REJECT — no agent_decisions must be written."""

    def __init__(self, violations: list[dict[str, str]]) -> None:
        super().__init__("guard rejected agent output")
        self.violations = violations


@dataclass(frozen=True)
class GuardValidationResult:
    """Outcome of ``ValidateAgentOutput``."""

    approved: bool
    violations: list[dict[str, str]]
    outcome: str = _OUTCOME_PASS
    sanitized_output: str = ""


def _grpc_target() -> str:
    explicit = os.environ.get("GUARD_SERVICE_GRPC_TARGET", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("GUARD_SERVICE_GRPC_HOST", "").strip()
    if not host:
        return ""
    port = os.environ.get("GUARD_SERVICE_GRPC_PORT", "7040")
    return f"{host}:{port}"


def _http_base_url() -> str:
    return os.environ.get("GUARD_SERVICE_HTTP_URL", "").strip().rstrip("/")


async def validate_agent_output(
    *,
    agent_id: str,
    run_id: str,
    output: AgentOutput,
    valid_symbols: set[str],
    raw_text: str | None = None,
    snapshot: dict[str, object] | None = None,
    tool_calls: list[dict[str, str]] | None = None,
) -> GuardValidationResult:
    """Validate agent output via guard-service (gRPC preferred, then HTTP) or inline.

    Args:
        agent_id: Agent identifier.
        run_id: Correlated ``agent_runs.id``.
        output: Parsed agent output.
        valid_symbols: Universe symbols from the snapshot.
        raw_text: Raw LLM JSON text sent to the guard.
        snapshot: Packaged snapshot dict for evidence/mandate checks.
        tool_calls: Tool invocations to validate against constitution.tools.

    Returns:
        :class:`GuardValidationResult` with approval flag, outcome, and violations.
    """
    raw = raw_text if raw_text is not None else output.model_dump_json()
    grpc_target = _grpc_target()
    if grpc_target:
        try:
            return await _validate_grpc(
                target=grpc_target,
                agent_id=agent_id,
                run_id=run_id,
                raw_output=raw,
                valid_symbols=valid_symbols,
                snapshot=snapshot,
                tool_calls=tool_calls,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("guard_grpc_failed_try_http", error=str(exc))

    http_url = _http_base_url()
    if http_url:
        try:
            return await _validate_http(
                base_url=http_url,
                agent_id=agent_id,
                run_id=run_id,
                raw_output=raw,
                output=output,
                valid_symbols=valid_symbols,
                snapshot=snapshot,
                tool_calls=tool_calls,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("guard_http_failed_fallback_inline", error=str(exc))

    try:
        validate_output(raw, valid_symbols)
        return GuardValidationResult(approved=True, violations=[], outcome=_OUTCOME_PASS)
    except GuardViolation as exc:
        return GuardValidationResult(
            approved=False,
            violations=[
                {"type": exc.db_violation_type, "detail": exc.detail, "kind": exc.kind},
            ],
            outcome=_OUTCOME_RETRY,
        )


async def _validate_grpc(
    *,
    target: str,
    agent_id: str,
    run_id: str,
    raw_output: str,
    valid_symbols: set[str],
    snapshot: dict[str, object] | None,
    tool_calls: list[dict[str, str]] | None,
) -> GuardValidationResult:
    """Call guard-service ``ValidateAgentOutput`` over gRPC."""
    request = guard_pb2.ValidateRequest(
        agent_id=agent_id,
        run_id=run_id,
        raw_output=raw_output,
        snapshot_json=json.dumps(snapshot) if snapshot else "",
        valid_symbols=sorted(valid_symbols),
    )
    for call in tool_calls or []:
        request.tool_calls.add(
            name=call.get("name", ""),
            arguments_json=call.get("arguments_json", call.get("arguments", "{}")),
        )
    async with grpc.aio.insecure_channel(target) as channel:
        stub = guard_pb2_grpc.GuardStub(channel)
        response = await stub.ValidateAgentOutput(request, timeout=30.0)
    outcome = _PROTO_OUTCOME_TO_STR.get(response.outcome, _OUTCOME_REJECT)
    violations = [
        {"type": v.type, "severity": v.severity, "detail": v.detail}
        for v in response.violations
    ]
    return GuardValidationResult(
        approved=outcome == _OUTCOME_PASS,
        violations=violations,
        outcome=outcome,
        sanitized_output=response.sanitized_output,
    )


async def _validate_http(
    *,
    base_url: str,
    agent_id: str,
    run_id: str,
    raw_output: str,
    output: AgentOutput,
    valid_symbols: set[str],
    snapshot: dict[str, object] | None,
    tool_calls: list[dict[str, str]] | None,
) -> GuardValidationResult:
    """POST to guard-service ``/v1/validate-agent-output`` HTTP bridge."""
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "run_id": run_id,
        "output": output.model_dump(),
        "raw_output": raw_output,
        "valid_symbols": sorted(valid_symbols),
        "snapshot": snapshot,
        "tool_calls": tool_calls or [],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{base_url}/v1/validate-agent-output", json=payload)
        response.raise_for_status()
        body = response.json()
    outcome = str(body.get("outcome", _OUTCOME_PASS))
    return GuardValidationResult(
        approved=bool(body.get("approved", outcome == _OUTCOME_PASS)),
        violations=list(body.get("violations") or []),
        outcome=outcome,
        sanitized_output=str(body.get("sanitized_output", "")),
    )
