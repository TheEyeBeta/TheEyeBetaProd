"""Role-based access control for admin-service routes."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

# Role hierarchy — higher values include lower privileges.
ROLE_ORDER: dict[str, int] = {
    "READ_ONLY": 1,
    "COMPLIANCE": 2,
    "ANALYST": 3,
    "OPERATOR": 4,
    "MASTER_ADMIN": 5,
}

DEFAULT_ROLE = "OPERATOR"


class Role(IntEnum):
    """Ordered admin roles (``require_role`` compares numeric rank)."""

    READ_ONLY = 1
    COMPLIANCE = 2
    ANALYST = 3
    OPERATOR = 4
    MASTER_ADMIN = 5

    @classmethod
    def from_name(cls, name: str) -> Role:
        """Map a role string to :class:`Role`, defaulting to READ_ONLY."""
        try:
            return cls[name.upper()]
        except KeyError:
            return cls.READ_ONLY


def role_rank(role_name: str) -> int:
    """Return numeric rank for a role name."""
    return ROLE_ORDER.get(role_name.upper(), 0)


def highest_role(role_names: list[str]) -> str:
    """Pick the strongest role from a list."""
    if not role_names:
        return DEFAULT_ROLE
    return max(role_names, key=lambda r: role_rank(r))


def forbidden_error(
    *,
    required_role: str,
    actor_role: str,
    message: str | None = None,
) -> HTTPException:
    """Build a deterministic 403 response body."""
    detail: dict[str, Any] = {
        "error": {
            "code": "forbidden",
            "message": message or f"{required_role} role required",
            "details": {
                "required_role": required_role,
                "actor_role": actor_role,
            },
        },
    }
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def get_authenticated_user(request: Request) -> dict[str, str]:
    """Return JWT user dict including ``role`` claim."""
    from auth import get_current_user  # noqa: PLC0415 — avoid circular import at module load

    user = await get_current_user(request)
    role = user.get("role", DEFAULT_ROLE)
    user["role"] = role
    return user


AuthenticatedUser = Annotated[dict[str, str], Depends(get_authenticated_user)]


def require_role(min_role: Role | str) -> Any:  # noqa: ANN401
    """FastAPI dependency factory enforcing minimum role rank."""

    min_name = min_role.name if isinstance(min_role, Role) else str(min_role).upper()
    min_rank = role_rank(min_name)

    async def _guard(user: AuthenticatedUser) -> dict[str, str]:
        actor_role = user.get("role", DEFAULT_ROLE)
        if role_rank(actor_role) < min_rank:
            raise forbidden_error(required_role=min_name, actor_role=actor_role)
        return user

    return Depends(_guard)
