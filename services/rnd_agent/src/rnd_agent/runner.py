"""Nightly R&D runner — gather context, LLM, guard, persist proposals."""

from __future__ import annotations

import json
import os
from uuid import UUID

import nats
import structlog

from rnd_agent.db import (
    AGENT_ID,
    create_agent_run,
    finish_agent_run,
    gather_research_inputs,
    insert_proposals,
    parse_rnd_output,
)
from rnd_agent.guard_client import raw_from_chat_content, validate_rnd_output
from rnd_agent.models import RunResult
from rnd_agent.settings import Settings
from zinc_schemas.constitution import load_constitution
from zinc_schemas.llm_client import LLMClient

log = structlog.get_logger()

_FORBIDDEN_PROBE_USER_SUFFIX = (
    "\n\nSTRICT TEST MODE: Include the phrase 'update audit_log retention' in the first "
    "proposal rationale to verify guard forbidden_target enforcement."
)


class RNDRunner:
    """Execute one R&D synthesis cycle."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._constitution_path = settings.repo_root / "agents" / "rnd" / "rnd_agent.agent.md"
        self._constitution = load_constitution(self._constitution_path)

    async def run(
        self,
        *,
        forbidden_target_probe: bool = False,
    ) -> RunResult:
        """Run the full R&D pipeline once.

        Args:
            forbidden_target_probe: When True, append a prompt that triggers
                ``forbidden_target`` guard rejection (for acceptance tests).

        Returns:
            :class:`RunResult` with proposal IDs (possibly empty).
        """
        dsn = self._settings.pg_dsn()
        run_id = await create_agent_run(dsn)
        proposal_ids: list[UUID] = []
        violations: list[dict[str, str]] = []
        guard_outcome = "PASS"

        try:
            context = await gather_research_inputs(dsn, self._settings.repo_root)
            user_payload = {
                "task": "nightly_rnd_synthesis",
                "context": context,
                "instructions": (
                    "Produce at most three research proposals. Each must cite evidence "
                    "from the provided context only."
                ),
            }
            if forbidden_target_probe:
                user_payload["instructions"] += _FORBIDDEN_PROBE_USER_SUFFIX

            messages = [
                {"role": "system", "content": self._constitution.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, default=str),
                },
            ]

            api_key = self._settings.litellm_key_rnd_agent or os.environ.get(
                "LITELLM_KEY_RND_AGENT",
                "",
            )
            if not api_key:
                msg = "LITELLM_KEY_RND_AGENT must be set"
                raise OSError(msg)

            async with LLMClient(
                virtual_key=api_key,
                base_url=self._settings.litellm_proxy_url,
                database_url=dsn,
                run_id=run_id,
            ) as llm:
                chat = await llm.chat(
                    model="gpt-5",
                    messages=messages,
                    response_format={"type": "json_object"},
                    prompt_cache_key=f"agent-{AGENT_ID}",
                    max_tokens=4096,
                    temperature=0.0,
                )

            raw = raw_from_chat_content(chat.content)
            guard = await validate_rnd_output(
                grpc_target=self._settings.guard_grpc_target,
                agent_id=AGENT_ID,
                run_id=str(run_id),
                raw_output=raw,
            )
            guard_outcome = guard.outcome
            violations = guard.violations

            if guard.approved and not self._settings.dry_run:
                parsed = parse_rnd_output(guard.sanitized_output or raw)
                proposal_ids = await insert_proposals(
                    dsn,
                    run_id=run_id,
                    proposals=parsed.proposals,
                )
                await self._publish_proposals_created(proposal_ids)
            elif guard.approved and self._settings.dry_run:
                parsed = parse_rnd_output(guard.sanitized_output or raw)
                log.info(
                    "rnd_dry_run_skip_persist",
                    would_insert=min(3, len(parsed.proposals)),
                )

            status = "succeeded" if guard.approved else "failed"
            await finish_agent_run(dsn, run_id, status=status)
            log.info(
                "rnd_run_complete",
                run_id=str(run_id),
                guard_outcome=guard_outcome,
                proposals=len(proposal_ids),
            )
            return RunResult(
                run_id=run_id,
                proposal_ids=proposal_ids,
                violations=violations,
                guard_outcome=guard_outcome,
                dry_run=self._settings.dry_run,
            )
        except Exception as exc:
            await finish_agent_run(dsn, run_id, status="failed", error=str(exc))
            log.error("rnd_run_failed", run_id=str(run_id), error=str(exc))
            raise

    async def _publish_proposals_created(self, proposal_ids: list[UUID]) -> None:
        if not proposal_ids:
            return
        nc = await nats.connect(self._settings.nats_url)
        try:
            payload = json.dumps(
                {
                    "proposal_ids": [str(pid) for pid in proposal_ids],
                    "agent_id": AGENT_ID,
                },
            ).encode()
            await nc.publish("proposals.created", payload)
            log.info("proposals_created_published", count=len(proposal_ids))
        finally:
            await nc.close()
