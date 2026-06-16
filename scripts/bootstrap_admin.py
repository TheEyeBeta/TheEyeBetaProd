"""Bootstrap admin-service DB users with RBAC roles.

Usage:
    uv run python scripts/bootstrap_admin.py \\
        --username admin \\
        --email you@theeyebeta.store \\
        --password 'yourpassword' \\
        --role MASTER_ADMIN

Idempotent: updates password and role assignment if the username already exists.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import bcrypt
import structlog
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
sys.path.insert(0, str(REPO_ROOT / "services" / "admin_service"))

from rbac import ROLE_ORDER  # noqa: E402

log = structlog.get_logger()

VALID_ROLES = frozenset(ROLE_ORDER)


def _database_url() -> str:
    """Resolve admin DB URL from environment."""
    raw = (
        os.environ.get("ADMIN_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MACRO_DATABASE_URL")
        or ""
    )
    if not raw:
        msg = "Set ADMIN_DATABASE_URL or DATABASE_URL"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


async def create_admin_user(
    *,
    username: str,
    email: str | None,
    password: str,
    role: str,
) -> None:
    """Insert or update an admin user and assign a single primary role."""
    role_upper = role.upper()
    if role_upper not in VALID_ROLES:
        msg = f"Invalid role {role!r}; expected one of {sorted(VALID_ROLES)}"
        raise ValueError(msg)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = await asyncpg.connect(_database_url())
    try:
        async with conn.transaction():
            user_id = await conn.fetchval(
                """
                INSERT INTO theeyebeta.admin_users (username, email, password_bcrypt)
                VALUES ($1, $2, $3)
                ON CONFLICT (username) DO UPDATE SET
                    email = EXCLUDED.email,
                    password_bcrypt = EXCLUDED.password_bcrypt,
                    is_active = true,
                    updated_at = now()
                RETURNING id
                """,
                username,
                email,
                password_hash,
            )
            role_id = await conn.fetchval(
                "SELECT id FROM theeyebeta.admin_roles WHERE name = $1",
                role_upper,
            )
            if role_id is None:
                msg = f"Role {role_upper} not found — run db migration 0026_admin_rbac"
                raise RuntimeError(msg)

            await conn.execute(
                "DELETE FROM theeyebeta.admin_user_roles WHERE user_id = $1",
                user_id,
            )
            await conn.execute(
                """
                INSERT INTO theeyebeta.admin_user_roles (user_id, role_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                user_id,
                role_id,
            )
        log.info(
            "admin_user_bootstrapped",
            username=username,
            role=role_upper,
            email=email,
        )
    finally:
        await conn.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Bootstrap admin-service RBAC user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--role",
        default="MASTER_ADMIN",
        choices=sorted(VALID_ROLES),
    )
    args = parser.parse_args()
    asyncio.run(
        create_admin_user(
            username=args.username,
            email=args.email,
            password=args.password,
            role=args.role,
        ),
    )
    print(f"OK: user {args.username!r} assigned role {args.role.upper()}")


if __name__ == "__main__":
    main()
