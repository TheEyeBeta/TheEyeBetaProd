"""Postgres access for admin_users, roles, and sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from db_compat import column_exists, table_exists

ROLE_MASTER_ADMIN = "MASTER_ADMIN"
ROLE_OPERATOR = "operator"

_USER_SELECT_TEMPLATE = """
SELECT
  u.id,
  u.username,
  {display_name_expr},
  u.email,
  {active_expr},
  {mfa_enabled_expr},
  {mfa_secret_version_expr},
  {last_login_at_expr},
  u.created_at,
  u.updated_at,
  COALESCE(
    array_agg(r.name ORDER BY r.name) FILTER (WHERE r.name IS NOT NULL),
    ARRAY[]::text[]
  ) AS roles
FROM theeyebeta.admin_users u
LEFT JOIN theeyebeta.admin_user_roles ur ON ur.user_id = u.id
LEFT JOIN theeyebeta.admin_roles r ON r.id = ur.role_id
"""


async def _admin_user_columns(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'theeyebeta'
           AND table_name = 'admin_users'
        """,
    )
    return {str(row["column_name"]) for row in rows}


def _user_expr(
    columns: set[str],
    column: str,
    *,
    fallback: str | None = None,
    default: str | None = None,
) -> str:
    if column in columns:
        return f"u.{column}"
    if fallback is not None and fallback in columns:
        return f"u.{fallback} AS {column}"
    if default is not None:
        return f"{default} AS {column}"
    return f"NULL AS {column}"


async def _user_select(conn: asyncpg.Connection) -> str:
    columns = await _admin_user_columns(conn)
    display_name_expr = (
        "u.display_name"
        if "display_name" in columns
        else "u.username AS display_name"
    )
    return _USER_SELECT_TEMPLATE.format(
        display_name_expr=display_name_expr,
        active_expr=_user_expr(columns, "active", fallback="is_active", default="true"),
        mfa_enabled_expr=_user_expr(
            columns,
            "mfa_enabled",
            fallback="totp_enabled",
            default="false",
        ),
        mfa_secret_version_expr=_user_expr(
            columns,
            "mfa_secret_version",
            default="0::smallint",
        ),
        last_login_at_expr=_user_expr(
            columns,
            "last_login_at",
            default="NULL::timestamptz",
        ),
    )


async def fetch_roles(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    description_expr = (
        "description"
        if await column_exists(conn, "theeyebeta", "admin_roles", "description")
        else "NULL::text AS description"
    )
    return await conn.fetch(
        f"SELECT id, name, {description_expr} FROM theeyebeta.admin_roles ORDER BY name",
    )


async def count_active_master_admins(
    conn: asyncpg.Connection,
    *,
    exclude_user_id: UUID | None = None,
) -> int:
    columns = await _admin_user_columns(conn)
    active_clause = (
        "u.active = true"
        if "active" in columns
        else "u.is_active = true"
        if "is_active" in columns
        else "true"
    )
    row = await conn.fetchrow(
        f"""
        SELECT COUNT(DISTINCT u.id)::int AS n
          FROM theeyebeta.admin_users u
          JOIN theeyebeta.admin_user_roles ur ON ur.user_id = u.id
          JOIN theeyebeta.admin_roles r ON r.id = ur.role_id
         WHERE {active_clause}
           AND r.name = $1
           AND ($2::uuid IS NULL OR u.id <> $2)
        """,
        ROLE_MASTER_ADMIN,
        exclude_user_id,
    )
    return int(row["n"]) if row else 0


async def list_users(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    user_select = await _user_select(conn)
    return await conn.fetch(
        f"""
        {user_select}
        GROUP BY u.id
        ORDER BY u.username
        """,
    )


async def get_user_by_id(conn: asyncpg.Connection, user_id: UUID) -> asyncpg.Record | None:
    user_select = await _user_select(conn)
    return await conn.fetchrow(
        f"""
        {user_select}
        WHERE u.id = $1
        GROUP BY u.id
        """,
        user_id,
    )


async def get_user_by_username(
    conn: asyncpg.Connection,
    username: str,
) -> asyncpg.Record | None:
    columns = await _admin_user_columns(conn)
    password_expr = _user_expr(
        columns,
        "password_hash",
        fallback="password_bcrypt",
        default="NULL::text",
    )
    return await conn.fetchrow(
        f"""
        SELECT u.id, u.username, {password_expr},
               {_user_expr(columns, "active", fallback="is_active", default="true")},
               {_user_expr(columns, "mfa_enabled", fallback="totp_enabled", default="false")},
               {_user_expr(columns, "mfa_secret_version", default="0::smallint")},
               {_user_expr(columns, "totp_secret", default="NULL::text")},
               {_user_expr(columns, "last_login_at", default="NULL::timestamptz")}
          FROM theeyebeta.admin_users u
         WHERE u.username = $1
        """,
        username,
    )


async def get_user_roles(conn: asyncpg.Connection, user_id: UUID) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT r.name
          FROM theeyebeta.admin_user_roles ur
          JOIN theeyebeta.admin_roles r ON r.id = ur.role_id
         WHERE ur.user_id = $1
         ORDER BY r.name
        """,
        user_id,
    )
    roles = [str(row["name"]) for row in rows]
    return roles or [ROLE_OPERATOR]


async def insert_user(
    conn: asyncpg.Connection,
    *,
    username: str,
    password_hash: str,
    display_name: str | None,
    email: str | None,
    roles: list[str],
    granted_by: str,
) -> asyncpg.Record:
    password_column = (
        "password_hash"
        if await column_exists(conn, "theeyebeta", "admin_users", "password_hash")
        else "password_bcrypt"
    )
    if await column_exists(conn, "theeyebeta", "admin_users", "display_name"):
        row = await conn.fetchrow(
            f"""
            INSERT INTO theeyebeta.admin_users
                (username, {password_column}, display_name, email)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            username,
            password_hash,
            display_name,
            email,
        )
    else:
        row = await conn.fetchrow(
            f"""
            INSERT INTO theeyebeta.admin_users
                (username, {password_column}, email)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            username,
            password_hash,
            email,
        )
    user_id = row["id"]
    for role_name in roles:
        await _grant_role(conn, user_id=user_id, role_name=role_name, granted_by=granted_by)
    detail = await get_user_by_id(conn, user_id)
    assert detail is not None
    return detail


async def update_user_fields(
    conn: asyncpg.Connection,
    user_id: UUID,
    *,
    display_name: str | None = None,
    email: str | None = None,
    patch_display: bool = False,
    patch_email: bool = False,
) -> asyncpg.Record | None:
    sets: list[str] = ["updated_at = now()"]
    values: list[Any] = []
    idx = 1
    if patch_display and await column_exists(conn, "theeyebeta", "admin_users", "display_name"):
        sets.append(f"display_name = ${idx}")
        values.append(display_name)
        idx += 1
    if patch_email:
        sets.append(f"email = ${idx}")
        values.append(email)
        idx += 1
    if len(values) == 0:
        return await get_user_by_id(conn, user_id)
    values.append(user_id)
    await conn.execute(
        f"UPDATE theeyebeta.admin_users SET {', '.join(sets)} WHERE id = ${idx}",
        *values,
    )
    return await get_user_by_id(conn, user_id)


async def set_user_active(
    conn: asyncpg.Connection,
    user_id: UUID,
    *,
    active: bool,
) -> asyncpg.Record | None:
    active_column = (
        "active"
        if await column_exists(conn, "theeyebeta", "admin_users", "active")
        else "is_active"
    )
    await conn.execute(
        f"""
        UPDATE theeyebeta.admin_users
           SET {active_column} = $2, updated_at = now()
         WHERE id = $1
        """,
        user_id,
        active,
    )
    return await get_user_by_id(conn, user_id)


async def _role_id(conn: asyncpg.Connection, role_name: str) -> int:
    row = await conn.fetchrow(
        "SELECT id FROM theeyebeta.admin_roles WHERE name = $1",
        role_name,
    )
    if row is None:
        msg = f"Unknown role: {role_name!r}"
        raise ValueError(msg)
    return int(row["id"])


async def _grant_role(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    role_name: str,
    granted_by: str,
) -> None:
    role_id = await _role_id(conn, role_name)
    if await column_exists(conn, "theeyebeta", "admin_user_roles", "granted_by"):
        await conn.execute(
            """
            INSERT INTO theeyebeta.admin_user_roles (user_id, role_id, granted_by)
            SELECT $1, $2, $3
             WHERE NOT EXISTS (
               SELECT 1 FROM theeyebeta.admin_user_roles
                WHERE user_id = $1 AND role_id = $2
             )
            """,
            user_id,
            role_id,
            granted_by,
        )
        return
    await conn.execute(
        """
        INSERT INTO theeyebeta.admin_user_roles (user_id, role_id)
        SELECT $1, $2
         WHERE NOT EXISTS (
           SELECT 1 FROM theeyebeta.admin_user_roles
            WHERE user_id = $1 AND role_id = $2
         )
        """,
        user_id,
        role_id,
    )


async def grant_role(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    role_name: str,
    granted_by: str,
) -> list[str]:
    await _grant_role(conn, user_id=user_id, role_name=role_name, granted_by=granted_by)
    return await get_user_roles(conn, user_id)


async def revoke_role(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    role_name: str,
) -> list[str]:
    role_id = await _role_id(conn, role_name)
    await conn.execute(
        """
        DELETE FROM theeyebeta.admin_user_roles
         WHERE user_id = $1 AND role_id = $2
        """,
        user_id,
        role_id,
    )
    return await get_user_roles(conn, user_id)


async def touch_last_login(conn: asyncpg.Connection, user_id: UUID) -> None:
    if not await column_exists(conn, "theeyebeta", "admin_users", "last_login_at"):
        await conn.execute(
            "UPDATE theeyebeta.admin_users SET updated_at = now() WHERE id = $1",
            user_id,
        )
        return
    await conn.execute(
        """
        UPDATE theeyebeta.admin_users
           SET last_login_at = now(), updated_at = now()
         WHERE id = $1
        """,
        user_id,
    )


async def reset_mfa(conn: asyncpg.Connection, user_id: UUID) -> asyncpg.Record | None:
    has_secret_col = await column_exists(conn, "theeyebeta", "admin_users", "totp_secret")
    secret_clause = ", totp_secret = NULL" if has_secret_col else ""
    if await column_exists(conn, "theeyebeta", "admin_users", "mfa_enabled"):
        await conn.execute(
            f"""
            UPDATE theeyebeta.admin_users
               SET mfa_enabled = false,
                   mfa_secret_version = mfa_secret_version + 1{secret_clause},
                   updated_at = now()
             WHERE id = $1
            """,
            user_id,
        )
        return await get_user_by_id(conn, user_id)
    if await column_exists(conn, "theeyebeta", "admin_users", "totp_enabled"):
        await conn.execute(
            f"""
            UPDATE theeyebeta.admin_users
               SET totp_enabled = false{secret_clause},
                   updated_at = now()
             WHERE id = $1
            """,
            user_id,
        )
        return await get_user_by_id(conn, user_id)
    return await get_user_by_id(conn, user_id)


async def set_pending_totp_secret(conn: asyncpg.Connection, user_id: UUID, secret: str) -> None:
    """Store a freshly generated TOTP secret, pending confirmation."""
    await conn.execute(
        """
        UPDATE theeyebeta.admin_users
           SET totp_secret = $2, updated_at = now()
         WHERE id = $1
        """,
        user_id,
        secret,
    )


async def get_totp_secret(conn: asyncpg.Connection, user_id: UUID) -> str | None:
    if not await column_exists(conn, "theeyebeta", "admin_users", "totp_secret"):
        return None
    return await conn.fetchval(
        "SELECT totp_secret FROM theeyebeta.admin_users WHERE id = $1",
        user_id,
    )


async def confirm_totp_enrollment(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Mark MFA enabled once the pending secret has been verified."""
    await conn.execute(
        """
        UPDATE theeyebeta.admin_users
           SET mfa_enabled = true, updated_at = now()
         WHERE id = $1
        """,
        user_id,
    )


async def insert_session(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    refresh_jti: str,
    user_agent: str | None,
    ip_address: str | None,
) -> None:
    if not await table_exists(conn, "theeyebeta", "admin_user_sessions"):
        return
    await conn.execute(
        """
        INSERT INTO theeyebeta.admin_user_sessions
            (user_id, refresh_jti, user_agent, ip_address)
        VALUES ($1, $2, $3, $4)
        """,
        user_id,
        refresh_jti,
        user_agent,
        ip_address,
    )


async def list_sessions(conn: asyncpg.Connection, user_id: UUID) -> list[asyncpg.Record]:
    if not await table_exists(conn, "theeyebeta", "admin_user_sessions"):
        return []
    return await conn.fetch(
        """
        SELECT id, refresh_jti, user_agent, ip_address,
               created_at, last_seen_at, revoked_at, revoked_by
          FROM theeyebeta.admin_user_sessions
         WHERE user_id = $1
         ORDER BY created_at DESC
        """,
        user_id,
    )


async def revoke_session(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    session_id: UUID,
    revoked_by: str,
) -> str | None:
    if not await table_exists(conn, "theeyebeta", "admin_user_sessions"):
        return None
    row = await conn.fetchrow(
        """
        UPDATE theeyebeta.admin_user_sessions
           SET revoked_at = now(), revoked_by = $3
         WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL
         RETURNING refresh_jti
        """,
        session_id,
        user_id,
        revoked_by,
    )
    return str(row["refresh_jti"]) if row else None


async def revoke_all_sessions(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    revoked_by: str,
) -> list[str]:
    if not await table_exists(conn, "theeyebeta", "admin_user_sessions"):
        return []
    rows = await conn.fetch(
        """
        UPDATE theeyebeta.admin_user_sessions
           SET revoked_at = now(), revoked_by = $2
         WHERE user_id = $1 AND revoked_at IS NULL
         RETURNING refresh_jti
        """,
        user_id,
        revoked_by,
    )
    return [str(row["refresh_jti"]) for row in rows]


async def fetch_user_audit(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    username: str,
    limit: int = 50,
) -> list[asyncpg.Record]:
    actor = f"admin-api:{username}"
    return await conn.fetch(
        """
        SELECT id, ts, actor, action, entity_type, entity_id, payload
          FROM theeyebeta.audit_log
         WHERE (entity_type = 'admin_user' AND entity_id = $1)
            OR actor = $2
         ORDER BY ts DESC
         LIMIT $3
        """,
        str(user_id),
        actor,
        limit,
    )
