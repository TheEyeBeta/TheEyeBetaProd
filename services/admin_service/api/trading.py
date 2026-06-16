"""Live trading approval and emergency halt APIs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from audit_log import write_audit_log
from deps import DbConn, NatsClient, RedisDep, RedisOpsDep
from fastapi import APIRouter, HTTPException, Request, status
from rbac import Role, require_role
from redis.asyncio import Redis
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    EmergencyHaltRequest,
    EmergencyHaltResponse,
    LiveApprovalRequest,
    LiveApprovalResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/trading", tags=["trading"])

_REDIS_CONFIRM_PREFIX = "admin:trading:confirm:"
_REDIS_HALT_KEY = "oms:submissions_paused:emergency"
_NATS_HALT_SUBJECT = "trading.emergency.halt"


def _actor(user: dict[str, str]) -> str:
    return f"admin-api:{user['sub']}"


async def issue_confirmation_token(redis: Redis, subject: str) -> str:
    """Store a short-lived confirmation token for dual-confirm flows."""
    token = str(uuid.uuid4())
    key = f"{_REDIS_CONFIRM_PREFIX}{subject}:{token}"
    await redis.set(key, "1", ex=300)
    return token


async def validate_confirmation_token(redis: Redis, subject: str, token: str) -> bool:
    """Validate and consume a confirmation token."""
    key = f"{_REDIS_CONFIRM_PREFIX}{subject}:{token}"
    value = await redis.get(key)
    if value:
        await redis.delete(key)
        return True
    return False


def register_trading_routes(limiter: Limiter) -> APIRouter:
    """Attach live trading control handlers."""

    @router.get(
        "/live-approval/token",
        summary="Issue live-approval confirmation token (MASTER_ADMIN)",
        description="Returns a short-lived token required by POST /admin/trading/live-approval.",
    )
    @limiter.limit("10/minute")
    async def live_approval_token(
        request: Request,  # noqa: ARG001
        redis: RedisDep,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> dict[str, str | int]:
        """Issue dual-confirm token for live trading approval."""
        token = await issue_confirmation_token(redis, user["sub"])
        return {"confirmation_token": token, "expires_in": 300}

    @router.post(
        "/live-approval",
        response_model=LiveApprovalResponse,
        summary="Enable/disable live trading (MASTER_ADMIN)",
    )
    @limiter.limit("5/minute")
    async def live_approval(
        request: Request,  # noqa: ARG001
        body: LiveApprovalRequest,
        conn: DbConn,
        redis: RedisDep,
        redis_ops: RedisOpsDep,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> LiveApprovalResponse:
        """Update accounts.metadata.live_approval with dual-confirm and audit."""
        if not body.consequences_acknowledged:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="consequences_acknowledged must be true",
            )
        if not await validate_confirmation_token(redis, user["sub"], body.confirmation_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "forbidden",
                        "message": "Invalid or expired confirmation_token",
                        "details": {},
                    },
                },
            )

        updated_at = datetime.now(tz=UTC)
        actor = _actor(user)
        result = await conn.execute(
            """
            UPDATE theeyebeta.accounts
               SET metadata = jsonb_set(
                       COALESCE(metadata, '{}'::jsonb),
                       '{live_approval}',
                       to_jsonb($1::boolean),
                       true
                   )
             WHERE mode = 'live'
            """,
            body.enable,
        )
        count = int(result.split()[-1]) if result else 0

        redis_live_ok = False
        try:
            if body.enable:
                await redis_ops.set("trading:live_enabled", "true")
            else:
                await redis_ops.delete("trading:live_enabled")
            redis_live_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("admin_live_approval_redis_failed", error=str(exc))

        await write_audit_log(
            conn,
            actor=actor,
            action="live_approval.update",
            entity_type="account",
            entity_id="live",
            payload={
                "enable": body.enable,
                "reason": body.reason,
                "override": True,
                "consequences_acknowledged": body.consequences_acknowledged,
                "confirmation_token_used": True,
                "actor": user["sub"],
                "updated_at": updated_at.isoformat(),
                "accounts_updated": count,
                "redis_live_enabled": body.enable if redis_live_ok else None,
            },
        )

        log.info(
            "admin_live_approval_updated",
            enable=body.enable,
            accounts=count,
            sub=user["sub"],
        )
        return LiveApprovalResponse(
            live_approval=body.enable,
            updated_at=updated_at,
            updated_by=user["sub"],
            accounts_updated=count,
        )

    @router.post(
        "/emergency-halt",
        response_model=EmergencyHaltResponse,
        summary="Emergency trading halt (MASTER_ADMIN)",
    )
    @limiter.limit("5/minute")
    async def emergency_halt(
        request: Request,  # noqa: ARG001
        body: EmergencyHaltRequest,
        conn: DbConn,
        nats: NatsClient,
        redis_ops: RedisOpsDep,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> EmergencyHaltResponse:
        """Halt all trading submissions via NATS + Redis gate."""
        if not body.consequences_acknowledged:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="consequences_acknowledged must be true",
            )

        halted_at = datetime.now(tz=UTC)
        actor = _actor(user)
        payload = {
            "reason": body.reason,
            "halted_by": user["sub"],
            "halted_at": halted_at.isoformat(),
            "override": True,
            "consequences_acknowledged": body.consequences_acknowledged,
        }

        nats_ok = False
        try:
            await nats.publish(_NATS_HALT_SUBJECT, json.dumps(payload).encode())
            nats_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("admin_emergency_halt_nats_failed", error=str(exc))

        redis_ok = False
        try:
            await redis_ops.set(_REDIS_HALT_KEY, "1")
            redis_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("admin_emergency_halt_redis_failed", error=str(exc))

        await write_audit_log(
            conn,
            actor=actor,
            action="halt.trading",
            entity_type="trading",
            entity_id="emergency",
            payload={
                **payload,
                "nats_published": nats_ok,
                "redis_paused": redis_ok,
            },
        )

        log.warning("admin_emergency_halt", sub=user["sub"], reason=body.reason)
        return EmergencyHaltResponse(
            halted=True,
            halted_at=halted_at,
            halted_by=user["sub"],
            nats_published=nats_ok,
            redis_paused=redis_ok,
        )

    return router
