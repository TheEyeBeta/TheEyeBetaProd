"""TOTP MFA enrollment, verification, and backup codes."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

import asyncpg
import bcrypt
import pyotp
import structlog
from audit_log import write_audit_log
from deps import DbConn, RedisDep, SettingsDep
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from settings import Settings


class MfaEnrollRequest(BaseModel):
    """Optional enrollment token for MASTER_ADMIN first-time setup."""

    model_config = ConfigDict(extra="forbid")

    enrollment_token: str | None = None


log = structlog.get_logger()

_TOKEN_TYPE_MFA_PENDING = "mfa_pending"
_TOKEN_TYPE_MFA_ENROLL = "mfa_enrollment"
_BACKUP_CODE_COUNT = 8


class MfaVerifyRequest(BaseModel):
    """Verify TOTP after password login."""

    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=10)
    totp_code: str = Field(min_length=6, max_length=8)


class MfaConfirmRequest(BaseModel):
    """Confirm TOTP enrollment with first valid code."""

    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=6, max_length=8)
    enrollment_token: str | None = None


class MfaBackupRequest(BaseModel):
    """Consume a one-time backup code."""

    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=10)
    backup_code: str = Field(min_length=8, max_length=32)


class MfaEnrollResponse(BaseModel):
    """TOTP enrollment payload."""

    model_config = ConfigDict(extra="forbid")

    secret: str
    provisioning_uri: str
    backup_codes: list[str]


async def fetch_mfa_state(
    conn: asyncpg.Connection,
    username: str,
) -> dict[str, Any] | None:
    """Return MFA columns for a user."""
    try:
        row = await conn.fetchrow(
            """
            SELECT totp_secret, totp_enabled, totp_backup_codes,
                   mfa_failed_attempts, mfa_locked_until
              FROM theeyebeta.admin_users
             WHERE username = $1 AND is_active
            """,
            username,
        )
    except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError):
        return None
    if row is None:
        return None
    return dict(row)


def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Return plaintext codes and bcrypt hashes."""
    plain = [secrets.token_hex(4).upper() for _ in range(_BACKUP_CODE_COUNT)]
    hashed = [bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode() for code in plain]
    return plain, hashed


async def _check_mfa_lock(mfa_state: dict[str, Any] | None) -> None:
    """Raise if user is temporarily locked out of MFA."""
    if mfa_state is None:
        return
    locked_until = mfa_state.get("mfa_locked_until")
    if locked_until and locked_until > datetime.now(tz=UTC):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="MFA locked due to failed attempts",
        )


async def _record_mfa_failure(conn: asyncpg.Connection, username: str, settings: Settings) -> None:
    """Increment failed MFA counter; lock after threshold."""
    row = await conn.fetchrow(
        """
        UPDATE theeyebeta.admin_users
           SET mfa_failed_attempts = mfa_failed_attempts + 1,
               mfa_locked_until = CASE
                 WHEN mfa_failed_attempts + 1 >= $2
                 THEN now() + interval '15 minutes'
                 ELSE mfa_locked_until
               END
         WHERE username = $1
     RETURNING mfa_failed_attempts
        """,
        username,
        settings.mfa_max_failed_attempts,
    )
    if row and row["mfa_failed_attempts"] >= settings.mfa_max_failed_attempts:
        await write_audit_log(
            conn,
            actor=f"admin-api:{username}",
            action="security.mfa_locked",
            entity_type="admin_user",
            entity_id=username,
            payload={"failed_attempts": row["mfa_failed_attempts"]},
        )


async def _reset_mfa_failures(conn: asyncpg.Connection, username: str) -> None:
    """Clear MFA failure counter on success."""
    await conn.execute(
        """
        UPDATE theeyebeta.admin_users
           SET mfa_failed_attempts = 0, mfa_locked_until = NULL
         WHERE username = $1
        """,
        username,
    )


def _verify_totp(secret: str, code: str) -> bool:
    """Validate TOTP code with one-step window."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def register_mfa_routes() -> APIRouter:
    """Attach MFA endpoints to the shared auth router."""
    from auth import (
        TokenResponse,
        _issue_tokens,
        _require_auth_config,
        _set_refresh_cookie,
        decode_access_token,
        router,
    )

    @router.post("/mfa/verify", response_model=TokenResponse)
    async def mfa_verify(
        request: Request,
        body: MfaVerifyRequest,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        conn: DbConn,
    ) -> TokenResponse:
        """Complete login with TOTP code."""
        _require_auth_config(settings)
        payload = decode_access_token(
            body.mfa_token, settings, expected_typ=_TOKEN_TYPE_MFA_PENDING
        )
        username = str(payload["sub"])
        role = str(payload.get("role", "READ_ONLY"))

        mfa_state = await fetch_mfa_state(conn, username)
        await _check_mfa_lock(mfa_state)
        if mfa_state is None or not mfa_state.get("totp_secret"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA not enrolled")

        if not _verify_totp(str(mfa_state["totp_secret"]), body.totp_code):
            await _record_mfa_failure(conn, username, settings)
            await write_audit_log(
                conn,
                actor=f"admin-api:{username}",
                action="security.mfa_failed",
                entity_type="admin_user",
                entity_id=username,
                payload={"method": "totp"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code"
            )

        await _reset_mfa_failures(conn, username)
        ip = request.client.host if request.client else None
        access, refresh, expires_in = await _issue_tokens(
            settings,
            username,
            redis,
            role=role,
            ip=ip,
            user_agent=request.headers.get("User-Agent"),
        )
        _set_refresh_cookie(response, refresh, settings)
        return TokenResponse(access_token=access, expires_in=expires_in, role=role)

    @router.post("/mfa/enroll", response_model=MfaEnrollResponse)
    async def mfa_enroll(
        body: MfaEnrollRequest,
        conn: DbConn,
        settings: SettingsDep,
        request: Request,
    ) -> MfaEnrollResponse:
        """Start TOTP enrollment (session or enrollment token)."""
        from auth import get_current_user

        username: str | None = None
        try:
            user = await get_current_user(request)
            username = user["sub"]
        except HTTPException:
            pass
        if body.enrollment_token:
            payload = decode_access_token(
                body.enrollment_token,
                settings,
                expected_typ=_TOKEN_TYPE_MFA_ENROLL,
            )
            username = str(payload["sub"])
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        secret = pyotp.random_base32()
        plain_codes, hashed_codes = _generate_backup_codes()
        await conn.execute(
            """
            UPDATE theeyebeta.admin_users
               SET totp_secret = $2,
                   totp_enabled = false,
                   totp_backup_codes = $3::text[]
             WHERE username = $1
            """,
            username,
            secret,
            hashed_codes,
        )
        uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="TheEyeBeta Admin")
        return MfaEnrollResponse(secret=secret, provisioning_uri=uri, backup_codes=plain_codes)

    @router.post("/mfa/confirm", status_code=status.HTTP_204_NO_CONTENT)
    async def mfa_confirm(
        body: MfaConfirmRequest,
        conn: DbConn,
        settings: SettingsDep,
        request: Request,
    ) -> Response:
        """Activate TOTP after verifying first code."""
        from auth import get_current_user

        username: str | None = None
        try:
            user = await get_current_user(request)
            username = user["sub"]
        except HTTPException:
            pass
        if body.enrollment_token:
            payload = decode_access_token(
                body.enrollment_token,
                settings,
                expected_typ=_TOKEN_TYPE_MFA_ENROLL,
            )
            username = str(payload["sub"])
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        row = await conn.fetchrow(
            """
            SELECT totp_secret FROM theeyebeta.admin_users
             WHERE username = $1 AND is_active
            """,
            username,
        )
        if row is None or not row["totp_secret"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enroll first")
        if not _verify_totp(str(row["totp_secret"]), body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code"
            )
        await conn.execute(
            """
            UPDATE theeyebeta.admin_users
               SET totp_enabled = true, totp_verified_at = now()
             WHERE username = $1
            """,
            username,
        )
        await write_audit_log(
            conn,
            actor=f"admin-api:{username}",
            action="security.mfa_enrolled",
            entity_type="admin_user",
            entity_id=username,
            payload={},
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/mfa/backup", response_model=TokenResponse)
    async def mfa_backup(
        request: Request,
        body: MfaBackupRequest,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        conn: DbConn,
    ) -> TokenResponse:
        """Complete login using a one-time backup code."""
        _require_auth_config(settings)
        payload = decode_access_token(
            body.mfa_token, settings, expected_typ=_TOKEN_TYPE_MFA_PENDING
        )
        username = str(payload["sub"])
        role = str(payload.get("role", "READ_ONLY"))
        mfa_state = await fetch_mfa_state(conn, username)
        await _check_mfa_lock(mfa_state)
        codes = list(mfa_state.get("totp_backup_codes") or []) if mfa_state else []
        matched_idx: int | None = None
        for idx, hashed in enumerate(codes):
            try:
                if bcrypt.checkpw(body.backup_code.encode(), hashed.encode()):
                    matched_idx = idx
                    break
            except ValueError:
                continue
        if matched_idx is None:
            await _record_mfa_failure(conn, username, settings)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid backup code"
            )
        remaining = [c for i, c in enumerate(codes) if i != matched_idx]
        await conn.execute(
            """
            UPDATE theeyebeta.admin_users
               SET totp_backup_codes = $2::text[], mfa_failed_attempts = 0, mfa_locked_until = NULL
             WHERE username = $1
            """,
            username,
            remaining,
        )
        ip = request.client.host if request.client else None
        access, refresh, expires_in = await _issue_tokens(
            settings,
            username,
            redis,
            role=role,
            ip=ip,
            user_agent=request.headers.get("User-Agent"),
        )
        _set_refresh_cookie(response, refresh, settings)
        return TokenResponse(access_token=access, expires_in=expires_in, role=role)

    return router
