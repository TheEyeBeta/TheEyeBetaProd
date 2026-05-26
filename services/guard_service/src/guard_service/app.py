"""Guard-service application — gRPC servicer, HTTP bridge, and validation orchestration."""

from __future__ import annotations

import asyncio
import json
import os
from concurrent import futures
from pathlib import Path
from typing import Any

import grpc
import nats
import structlog
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from zinc_proto import guard_pb2, guard_pb2_grpc
from zinc_schemas.constitution import load_all_constitutions, resolve_agents_dir

from guard_service.creative_classifier import CreativeContentClassifier
from guard_service.db import count_violations_for_run, insert_violations
from guard_service.validator import ConstitutionGuard, Outcome, ValidationResult

log = structlog.get_logger()

_GRPC_HOST = os.environ.get("GUARD_SERVICE_GRPC_HOST", "127.0.0.1")
_GRPC_PORT = int(os.environ.get("GUARD_SERVICE_GRPC_PORT", "7040"))
_HTTP_HOST = os.environ.get("GUARD_SERVICE_HTTP_HOST", "127.0.0.1")
_HTTP_PORT = int(os.environ.get("GUARD_SERVICE_HTTP_PORT", "8005"))


def build_guard() -> ConstitutionGuard:
    """Load constitutions and optional creative classifier."""
    repo_root = Path(__file__).resolve().parents[4]
    agents_dir = resolve_agents_dir(repo_root)
    constitutions = load_all_constitutions(agents_dir)
    classifier: CreativeContentClassifier | None = None
    disable_creative = os.environ.get("GUARD_DISABLE_CREATIVE_CLASSIFIER", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if (
        not disable_creative
        and os.environ.get("LITELLM_KEY_GUARD_SERVICE_CLASSIFIER", "").startswith("sk-")
    ):
        classifier = CreativeContentClassifier()
    return ConstitutionGuard(constitutions, creative_classifier=classifier)


class GuardServicer(guard_pb2_grpc.GuardServicer):
    """gRPC servicer for ``ValidateAgentOutput``."""

    def __init__(self, guard: ConstitutionGuard) -> None:
        self._guard = guard

    async def ValidateAgentOutput(  # noqa: N802
        self,
        request: guard_pb2.ValidateRequest,
        context: grpc.aio.ServicerContext,
    ) -> guard_pb2.ValidateResponse:
        """Validate raw agent output against the agent constitution."""
        _ = context
        result = await validate_request(self._guard, request)
        return to_proto_response(result)


async def validate_request(
    guard: ConstitutionGuard,
    request: guard_pb2.ValidateRequest,
) -> ValidationResult:
    """Run constitution guard and persist violations."""
    snapshot: dict[str, Any] | None = None
    if request.snapshot_json:
        snapshot = json.loads(request.snapshot_json)
    valid_symbols = set(request.valid_symbols) if request.valid_symbols else None
    tool_calls = [
        {"name": tc.name, "arguments_json": tc.arguments_json}
        for tc in request.tool_calls
    ]
    prior = await count_violations_for_run(request.run_id)
    result = await guard.validate(
        agent_id=request.agent_id,
        raw_output=request.raw_output,
        tool_calls=tool_calls,
        valid_symbols=valid_symbols,
        snapshot=snapshot,
        prior_violation_count=prior,
    )
    await insert_violations(
        agent_id=request.agent_id,
        run_id=request.run_id,
        violations=result.violations,
        outcome=result.outcome,
    )
    if result.outcome == Outcome.REJECT:
        await publish_escalation(request.agent_id, request.run_id, result)
    return result


async def publish_escalation(
    agent_id: str,
    run_id: str,
    result: ValidationResult,
) -> None:
    """Publish ``agents.violations.escalated.{agent_id}`` on REJECT."""
    nats_url = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
    subject = f"agents.violations.escalated.{agent_id}"
    payload = json.dumps(
        {
            "agent_id": agent_id,
            "run_id": run_id,
            "violations": [v.to_dict() for v in result.violations],
            "outcome": "REJECT",
        },
    ).encode()
    nc = await nats.connect(nats_url)
    try:
        await nc.publish(subject, payload)
        log.info("guard_escalation_published", subject=subject, run_id=run_id)
    finally:
        await nc.close()


def to_proto_response(result: ValidationResult) -> guard_pb2.ValidateResponse:
    """Map internal validation result to protobuf response."""
    outcome_map = {
        Outcome.PASS: guard_pb2.PASS,
        Outcome.RETRY: guard_pb2.RETRY,
        Outcome.ESCALATE: guard_pb2.ESCALATE,
        Outcome.REJECT: guard_pb2.REJECT,
    }
    return guard_pb2.ValidateResponse(
        outcome=outcome_map[result.outcome],
        violations=[
            guard_pb2.Violation(type=v.type, severity=v.severity, detail=v.detail)
            for v in result.violations
        ],
        sanitized_output=result.sanitized_output,
    )


class ValidateAgentOutputBody(BaseModel):
    """HTTP bridge body matching agent-runtime guard_client."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    run_id: str
    output: dict[str, Any] | None = None
    raw_output: str | None = None
    valid_symbols: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any] | None = None
    tool_calls: list[dict[str, str]] = Field(default_factory=list)


def create_http_app(guard: ConstitutionGuard) -> FastAPI:
    """FastAPI app exposing health and HTTP validation bridge."""
    app = FastAPI(title="guard-service", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "guard-service"}

    @app.post("/v1/validate-agent-output")
    async def validate_agent_output_endpoint(body: ValidateAgentOutputBody) -> dict[str, Any]:
        raw = body.raw_output
        if raw is None and body.output is not None:
            raw = json.dumps(body.output)
        if raw is None:
            return {"approved": False, "violations": [{"type": "schema", "detail": "empty"}]}
        request = guard_pb2.ValidateRequest(
            agent_id=body.agent_id,
            run_id=body.run_id,
            raw_output=raw,
            snapshot_json=json.dumps(body.snapshot) if body.snapshot else "",
            valid_symbols=body.valid_symbols,
        )
        for call in body.tool_calls:
            request.tool_calls.add(
                name=call.get("name", ""),
                arguments_json=call.get("arguments_json", call.get("arguments", "{}")),
            )
        result = await validate_request(guard, request)
        return {
            "approved": result.outcome == Outcome.PASS,
            "outcome": result.outcome.name,
            "violations": [v.to_dict() for v in result.violations],
            "sanitized_output": result.sanitized_output,
        }

    return app


async def serve_grpc(guard: ConstitutionGuard) -> grpc.aio.Server:
    """Start the gRPC server."""
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    guard_pb2_grpc.add_GuardServicer_to_server(GuardServicer(guard), server)
    listen = f"{_GRPC_HOST}:{_GRPC_PORT}"
    server.add_insecure_port(listen)
    await server.start()
    log.info("guard_grpc_started", listen=listen)
    return server


async def run_servers() -> None:
    """Run gRPC and HTTP servers concurrently."""
    guard = build_guard()
    grpc_server = await serve_grpc(guard)
    config = uvicorn.Config(
        create_http_app(guard),
        host=_HTTP_HOST,
        port=_HTTP_PORT,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(config)
    http_task = asyncio.create_task(uvicorn_server.serve())
    try:
        await grpc_server.wait_for_termination()
    finally:
        http_task.cancel()


def main() -> None:
    """Entrypoint for ``python -m guard_service`` or service main."""
    asyncio.run(run_servers())
