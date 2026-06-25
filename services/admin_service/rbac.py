"""RBAC dependencies and dangerous-action guards."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auth import CurrentUser

ROLE_OPERATOR = "operator"
ROLE_MASTER_ADMIN = "MASTER_ADMIN"


class DangerousActionRequest(BaseModel):
    """Body for MASTER_ADMIN mutations that require explicit confirmation."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool = Field(
        description="Must be true — operator typed confirmation in UI.",
    )


class RoleChangeRequest(DangerousActionRequest):
    """Grant or revoke a role with audit reason."""

    role: str = Field(min_length=1, max_length=64)
    allow_final_master_removal: bool = Field(
        default=False,
        description="Required to remove the last active MASTER_ADMIN.",
    )


async def require_master_admin(user: CurrentUser) -> dict[str, object]:
    """Allow only operators with MASTER_ADMIN in JWT roles."""
    roles = user.get("roles") or [ROLE_OPERATOR]
    if ROLE_MASTER_ADMIN not in roles:
        raise HTTPException(status_code=403, detail="MASTER_ADMIN role required")
    return user


MasterAdminUser = Annotated[dict[str, object], Depends(require_master_admin)]


def require_dangerous_confirm(
    body: DangerousActionRequest,
    x_confirm: str | None = Header(default=None, alias="X-Confirm"),
) -> None:
    """Validate dangerous mutation confirmation headers and body."""
    if not body.confirm:
        raise HTTPException(status_code=422, detail="confirm must be true")
    if (x_confirm or "").lower() != "true":
        raise HTTPException(status_code=422, detail="X-Confirm: true header is required")


def actor_from_user(user: dict[str, object]) -> str:
    return f"admin-api:{user['sub']}"
