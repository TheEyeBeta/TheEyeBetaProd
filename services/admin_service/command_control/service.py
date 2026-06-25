"""Command console orchestration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from command_control.executor import CommandExecutionContext, CommandExecutor, build_preview
from command_control.parser import parse_command
from command_control.registry import COMMANDS
from command_control.repository import CommandRepository
from rbac import ROLE_MASTER_ADMIN, ROLE_OPERATOR
from settings import Settings
from zinc_schemas.admin_dto import (
    CommandDefinitionEntry,
    CommandListResponse,
    CommandPreviewRequest,
    CommandPreviewResponse,
    CommandRunDetailResponse,
    CommandRunRequest,
    CommandRunResponse,
    CommandRunSummaryEntry,
    CommandRunsListResponse,
)

log = structlog.get_logger()


class CommandControlService:
    """Allowlisted CLI parity — preview and execute only mapped backend APIs."""

    def __init__(
        self,
        conn: Any,
        settings: Settings,
        *,
        redis: Any | None = None,
        nats: Any | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._redis = redis
        self._nats = nats
        self._repo = CommandRepository(conn)
        self._executor = CommandExecutor()

    @staticmethod
    def _user_roles(user: dict[str, Any]) -> list[str]:
        return list(user.get("roles") or [ROLE_OPERATOR])

    @classmethod
    def _role_allowed(cls, user: dict[str, Any], role_required: str) -> bool:
        roles = cls._user_roles(user)
        if role_required == ROLE_MASTER_ADMIN:
            return ROLE_MASTER_ADMIN in roles
        return ROLE_OPERATOR in roles or ROLE_MASTER_ADMIN in roles

    @staticmethod
    def list_commands() -> CommandListResponse:
        return CommandListResponse(
            commands=[
                CommandDefinitionEntry(
                    id=cmd.id,
                    example=cmd.example,
                    description=cmd.description,
                    role_required=cmd.role_required,
                    backend_route=cmd.backend_route,
                    dangerous=cmd.dangerous,
                    confirmation_required=cmd.confirmation_required,
                    reason_required=cmd.reason_required,
                    audit_category=cmd.audit_category,
                    preview_output=cmd.preview_output,
                    rollback_note=cmd.rollback_note,
                )
                for cmd in COMMANDS
            ],
        )

    async def preview(
        self,
        body: CommandPreviewRequest,
        *,
        user: dict[str, Any],
    ) -> CommandPreviewResponse:
        try:
            parsed = parse_command(body.command)
        except ValueError as exc:
            return CommandPreviewResponse(
                command_text=body.command,
                allowed=False,
                denial_reason=str(exc),
            )
        allowed = self._role_allowed(user, parsed.definition.role_required)
        denial = None if allowed else f"Requires role {parsed.definition.role_required}"
        preview_payload = build_preview(parsed, allowed=allowed, denial=denial)
        run_id = await self._repo.create_run(
            command_id=parsed.definition.id,
            command_text=parsed.raw,
            actor=f"admin-api:{user['sub']}",
            reason=body.reason,
            status="preview",
            backend_route=parsed.definition.backend_route,
            audit_category=parsed.definition.audit_category,
            preview=preview_payload,
        )
        return CommandPreviewResponse(
            run_id=run_id,
            command_id=preview_payload["command_id"],
            command_text=parsed.raw,
            description=preview_payload["description"],
            role_required=preview_payload["role_required"],
            backend_route=preview_payload["backend_route"],
            dangerous=preview_payload["dangerous"],
            confirmation_required=preview_payload["confirmation_required"],
            reason_required=preview_payload["reason_required"],
            audit_category=preview_payload["audit_category"],
            preview_output=preview_payload["preview_output"],
            rollback_note=preview_payload["rollback_note"],
            consequence_preview=preview_payload["consequence_preview"],
            params=preview_payload.get("params") or {},
            allowed=allowed,
            denial_reason=denial,
        )

    async def run(
        self,
        body: CommandRunRequest,
        *,
        user: dict[str, Any],
    ) -> CommandRunResponse:
        try:
            parsed = parse_command(body.command)
        except ValueError as exc:
            run_id = await self._repo.create_run(
                command_id="unknown",
                command_text=body.command,
                actor=f"admin-api:{user['sub']}",
                reason=body.reason,
                status="rejected",
                backend_route="",
                audit_category="unknown",
                error=str(exc),
            )
            msg = str(exc)
            raise ValueError(msg) from exc

        definition = parsed.definition
        if not self._role_allowed(user, definition.role_required):
            msg = f"Requires role {definition.role_required}"
            raise ValueError(msg)

        if definition.reason_required and not (body.reason or "").strip():
            msg = "reason is required for this command"
            raise ValueError(msg)

        if definition.confirmation_required and not body.confirm:
            msg = "confirm must be true for this command"
            raise ValueError(msg)

        actor = f"admin-api:{user['sub']}"
        reason = (body.reason or "").strip() or "command console"
        run_id = await self._repo.create_run(
            command_id=definition.id,
            command_text=parsed.raw,
            actor=actor,
            reason=reason,
            status="running",
            backend_route=definition.backend_route,
            audit_category=definition.audit_category,
            preview=build_preview(parsed, allowed=True),
        )

        ctx = CommandExecutionContext(
            conn=self._conn,
            settings=self._settings,
            redis=self._redis,
            nats=self._nats,
            actor=actor,
            reason=reason,
        )
        try:
            result = await self._executor.execute(parsed, ctx)
        except Exception as exc:
            await self._repo.complete_run(run_id, status="failed", result={}, error=str(exc)[:500])
            raise ValueError(str(exc)) from exc

        await self._repo.complete_run(run_id, status="succeeded", result=result)
        log.info("command_run_succeeded", command_id=definition.id, run_id=str(run_id), sub=user["sub"])
        return CommandRunResponse(
            run_id=run_id,
            command_id=definition.id,
            command_text=parsed.raw,
            status="succeeded",
            backend_route=definition.backend_route,
            audit_category=definition.audit_category,
            result=result,
            audited=True,
        )

    async def list_runs(self, *, limit: int = 50) -> CommandRunsListResponse:
        rows = await self._repo.list_runs(limit=limit)
        return CommandRunsListResponse(
            runs=[
                CommandRunSummaryEntry(
                    id=row["id"],
                    command_id=row["command_id"],
                    command_text=row["command_text"],
                    actor=row["actor"],
                    status=row["status"],
                    backend_route=row["backend_route"],
                    audit_category=row["audit_category"],
                    created_at=row["created_at"],
                    completed_at=row.get("completed_at"),
                )
                for row in rows
            ],
        )

    async def get_run(self, run_id: UUID) -> CommandRunDetailResponse:
        row = await self._repo.get_run(run_id)
        if row is None:
            msg = f"Command run {run_id} not found"
            raise ValueError(msg)
        return CommandRunDetailResponse(
            id=row["id"],
            command_id=row["command_id"],
            command_text=row["command_text"],
            actor=row["actor"],
            reason=row.get("reason"),
            status=row["status"],
            backend_route=row["backend_route"],
            audit_category=row["audit_category"],
            preview=row.get("preview") or {},
            result=row.get("result") or {},
            error=row.get("error"),
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
            audit_link="/admin/audit",
        )
