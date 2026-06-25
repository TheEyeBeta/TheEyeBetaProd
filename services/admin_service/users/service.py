"""Admin users service — RBAC rules, audit, session revoke."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
import bcrypt
from audit_log import write_audit_log
from fastapi import HTTPException, status
from redis.asyncio import Redis

from rbac import ROLE_MASTER_ADMIN, ROLE_OPERATOR
from users import repository as repo
from zinc_schemas.admin_dto import (
    AdminUserAuditEntry,
    AdminUserCreateRequest,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserRoleListResponse,
    AdminUserSessionEntry,
    AdminUserSessionListResponse,
    AdminUserSummary,
    AdminUserRolesChangeResponse,
)


class AdminUsersService:
    """Operator user control plane."""

    def __init__(self, conn: asyncpg.Connection, redis: Redis | None = None) -> None:
        self._conn = conn
        self._redis = redis

    async def list_users(self) -> AdminUserListResponse:
        rows = await repo.list_users(self._conn)
        return AdminUserListResponse(users=[self._row_to_summary(r) for r in rows])

    async def get_user(self, user_id: UUID) -> AdminUserDetailResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        audit_rows = await repo.fetch_user_audit(
            self._conn,
            user_id=user_id,
            username=row["username"],
            limit=50,
        )
        return AdminUserDetailResponse(
            **self._row_to_summary(row).model_dump(),
            audit_history=[self._audit_row(r) for r in audit_rows],
        )

    async def create_user(
        self,
        body: AdminUserCreateRequest,
        *,
        actor: str,
    ) -> AdminUserDetailResponse:
        existing = await repo.get_user_by_username(self._conn, body.username)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")
        roles = self._normalize_roles(body.roles)
        password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        async with self._conn.transaction():
            row = await repo.insert_user(
                self._conn,
                username=body.username,
                password_hash=password_hash,
                display_name=body.display_name,
                email=body.email,
                roles=roles,
                granted_by=actor,
            )
            await write_audit_log(
                self._conn,
                actor=actor,
                action="create.admin_user",
                entity_type="admin_user",
                entity_id=str(row["id"]),
                payload={
                    "username": body.username,
                    "roles": roles,
                    "reason": body.reason,
                },
            )
        return await self.get_user(row["id"])

    async def patch_user(
        self,
        user_id: UUID,
        body: AdminUserPatchRequest,
        *,
        actor: str,
    ) -> AdminUserDetailResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        async with self._conn.transaction():
            await repo.update_user_fields(
                self._conn,
                user_id,
                display_name=body.display_name,
                email=body.email,
                patch_display=body.display_name is not None,
                patch_email=body.email is not None,
            )
            await write_audit_log(
                self._conn,
                actor=actor,
                action="update.admin_user",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload=body.model_dump(exclude_none=True),
            )
        return await self.get_user(user_id)

    async def disable_user(
        self,
        user_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> AdminUserDetailResponse:
        return await self._set_active(user_id, active=False, actor=actor, reason=reason)

    async def enable_user(
        self,
        user_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> AdminUserDetailResponse:
        return await self._set_active(user_id, active=True, actor=actor, reason=reason)

    async def list_roles(self, user_id: UUID) -> AdminUserRoleListResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        roles = list(row["roles"] or [])
        return AdminUserRoleListResponse(user_id=user_id, roles=roles)

    async def grant_role(
        self,
        user_id: UUID,
        *,
        role: str,
        actor: str,
        reason: str,
    ) -> AdminUserRolesChangeResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        async with self._conn.transaction():
            roles = await repo.grant_role(
                self._conn,
                user_id=user_id,
                role_name=role,
                granted_by=actor,
            )
            await write_audit_log(
                self._conn,
                actor=actor,
                action="grant.admin_user_role",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={"role": role, "reason": reason, "roles": roles},
            )
        return AdminUserRolesChangeResponse(user_id=user_id, roles=roles)

    async def revoke_role(
        self,
        user_id: UUID,
        *,
        role: str,
        actor: str,
        reason: str,
        allow_final_master_removal: bool = False,
    ) -> AdminUserRolesChangeResponse:
        if role == ROLE_MASTER_ADMIN:
            await self._guard_final_master_admin(user_id, allow_final_master_removal)
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        async with self._conn.transaction():
            roles = await repo.revoke_role(self._conn, user_id=user_id, role_name=role)
            if not roles:
                roles = [ROLE_OPERATOR]
            await write_audit_log(
                self._conn,
                actor=actor,
                action="revoke.admin_user_role",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={
                    "role": role,
                    "reason": reason,
                    "roles": roles,
                    "allow_final_master_removal": allow_final_master_removal,
                },
            )
        return AdminUserRolesChangeResponse(user_id=user_id, roles=roles)

    async def list_sessions(self, user_id: UUID) -> AdminUserSessionListResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        rows = await repo.list_sessions(self._conn, user_id)
        return AdminUserSessionListResponse(
            user_id=user_id,
            sessions=[self._session_row(r) for r in rows],
        )

    async def revoke_all_sessions(
        self,
        user_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> AdminUserSessionListResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        async with self._conn.transaction():
            jtis = await repo.revoke_all_sessions(
                self._conn,
                user_id=user_id,
                revoked_by=actor,
            )
            await self._revoke_refresh_tokens(jtis)
            await write_audit_log(
                self._conn,
                actor=actor,
                action="revoke_all.admin_user_sessions",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={"reason": reason, "session_count": len(jtis)},
            )
        return await self.list_sessions(user_id)

    async def reset_mfa(
        self,
        user_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> AdminUserDetailResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        async with self._conn.transaction():
            await repo.reset_mfa(self._conn, user_id)
            await write_audit_log(
                self._conn,
                actor=actor,
                action="reset_mfa.admin_user",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={"reason": reason},
            )
        return await self.get_user(user_id)

    async def enroll_mfa(
        self,
        user_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, str]:
        """Generate a pending TOTP secret; MFA stays disabled until confirmed."""
        import pyotp

        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        secret = pyotp.random_base32()
        async with self._conn.transaction():
            await repo.set_pending_totp_secret(self._conn, user_id, secret)
            await write_audit_log(
                self._conn,
                actor=actor,
                action="mfa_enroll.admin_user",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={"reason": reason},
            )
        otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=row["username"],
            issuer_name="TheEyeBeta Admin",
        )
        return {"secret": secret, "otpauth_uri": otpauth_uri}

    async def confirm_mfa(
        self,
        user_id: UUID,
        *,
        code: str,
        actor: str,
    ) -> AdminUserDetailResponse:
        """Verify the pending TOTP secret with one code and enable MFA."""
        import pyotp

        secret = await repo.get_totp_secret(self._conn, user_id)
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pending MFA enrollment — call /mfa/enroll first",
            )
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
        async with self._conn.transaction():
            await repo.confirm_totp_enrollment(self._conn, user_id)
            await write_audit_log(
                self._conn,
                actor=actor,
                action="mfa_confirm.admin_user",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={},
            )
        return await self.get_user(user_id)

    async def authenticate(
        self,
        username: str,
        password: str,
    ) -> tuple[UUID | None, str, list[str], bool, str | None]:
        """Return (user_id, username, roles, mfa_enabled, totp_secret) after password verify."""
        row = await repo.get_user_by_username(self._conn, username)
        if row is not None:
            if not row["active"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )
            user_id = row["id"]
            roles = await repo.get_user_roles(self._conn, user_id)
            await repo.touch_last_login(self._conn, user_id)
            return user_id, row["username"], roles, bool(row["mfa_enabled"]), row["totp_secret"]
        return None, username, [], False, None

    async def record_session(
        self,
        *,
        user_id: UUID,
        refresh_jti: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> None:
        await repo.insert_session(
            self._conn,
            user_id=user_id,
            refresh_jti=refresh_jti,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def _set_active(
        self,
        user_id: UUID,
        *,
        active: bool,
        actor: str,
        reason: str,
    ) -> AdminUserDetailResponse:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not active and ROLE_MASTER_ADMIN in (row["roles"] or []):
            await self._guard_final_master_admin(user_id, allow_final=False)
        async with self._conn.transaction():
            await repo.set_user_active(self._conn, user_id, active=active)
            if not active:
                jtis = await repo.revoke_all_sessions(
                    self._conn,
                    user_id=user_id,
                    revoked_by=actor,
                )
                await self._revoke_refresh_tokens(jtis)
            await write_audit_log(
                self._conn,
                actor=actor,
                action="enable.admin_user" if active else "disable.admin_user",
                entity_type="admin_user",
                entity_id=str(user_id),
                payload={"reason": reason, "active": active},
            )
        return await self.get_user(user_id)

    async def _guard_final_master_admin(
        self,
        user_id: UUID,
        allow_final: bool,
    ) -> None:
        row = await repo.get_user_by_id(self._conn, user_id)
        if row is None:
            return
        if ROLE_MASTER_ADMIN not in (row["roles"] or []):
            return
        remaining = await repo.count_active_master_admins(
            self._conn,
            exclude_user_id=user_id,
        )
        if remaining == 0 and not allow_final:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot remove the last active MASTER_ADMIN. "
                    "Grant MASTER_ADMIN to another user first, or pass allow_final_master_removal."
                ),
            )

    async def _revoke_refresh_tokens(self, jtis: list[str]) -> None:
        if self._redis is None:
            return
        for jti in jtis:
            await self._redis.delete(f"admin:refresh:{jti}")

    @staticmethod
    def _normalize_roles(roles: list[str]) -> list[str]:
        normalized = sorted(set(roles) | {ROLE_OPERATOR})
        return normalized


    @staticmethod
    def _row_to_summary(row: asyncpg.Record) -> AdminUserSummary:
        roles = list(row["roles"] or [ROLE_OPERATOR])
        return AdminUserSummary(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            email=row["email"],
            active=row["active"],
            mfa_enabled=row["mfa_enabled"],
            roles=roles,
            last_login_at=row["last_login_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _session_row(row: asyncpg.Record) -> AdminUserSessionEntry:
        return AdminUserSessionEntry(
            id=row["id"],
            user_agent=row["user_agent"],
            ip_address=row["ip_address"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            active=row["revoked_at"] is None,
            revoked_at=row["revoked_at"],
        )

    @staticmethod
    def _audit_row(row: asyncpg.Record) -> AdminUserAuditEntry:
        payload = row["payload"]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        safe_payload = AdminUsersService._redact_payload(payload if isinstance(payload, dict) else {})
        return AdminUserAuditEntry(
            id=int(row["id"]),
            ts=row["ts"],
            actor=row["actor"],
            action=row["action"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            payload_summary=safe_payload,
        )

    @staticmethod
    def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"password", "password_hash", "token", "secret", "mfa_secret"}
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if key.lower() in forbidden:
                continue
            out[key] = value
        return out
