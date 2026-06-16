"""JWT authentication routes for admin-service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import asyncpg
import bcrypt
import jwt
import structlog
from audit_log import write_audit_log
from auth_sessions import (
    consume_refresh_token,
    list_sessions,
    revoke_all_sessions,
    revoke_refresh,
    store_refresh_session,
)
from deps import DbConn, RedisDep, SettingsDep
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from rbac import DEFAULT_ROLE, Role, highest_role, require_role
from redis.asyncio import Redis
from settings import Settings
from slowapi import Limiter

log = structlog.get_logger()

router = APIRouter(tags=["auth"])

_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"
_TOKEN_TYPE_MFA_PENDING = "mfa_pending"
_TOKEN_TYPE_MFA_ENROLL = "mfa_enrollment"


async def get_current_user(request: Request) -> dict[str, str]:
    """Validate Bearer access JWT and return ``{sub, role}``."""
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    settings: Settings = request.app.state.settings
    payload = decode_access_token(token, settings)
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )
    role = payload.get("role", DEFAULT_ROLE)
    if not isinstance(role, str):
        role = DEFAULT_ROLE
    return {"sub": sub, "role": role}


CurrentUser = Annotated[dict[str, str], Depends(get_current_user)]


class LoginRequest(BaseModel):
    """Operator login payload."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """Access token returned in JSON; refresh is httpOnly cookie only."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = DEFAULT_ROLE


class RefreshResponse(BaseModel):
    """Rotated access token."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = DEFAULT_ROLE


class LoginResponse(BaseModel):
    """Login may return tokens directly or require MFA."""

    model_config = ConfigDict(extra="forbid")

    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    role: str | None = None
    mfa_required: bool = False
    mfa_token: str | None = None
    mfa_enrollment_required: bool = False
    enrollment_token: str | None = None


class CurrentUserResponse(BaseModel):
    """``GET /admin/auth/me`` payload."""

    model_config = ConfigDict(extra="forbid")

    username: str
    role: str


class SessionEntry(BaseModel):
    """One active refresh session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    issued_at: str | None = None
    last_used_at: str | None = None
    ip: str | None = None
    user_agent: str | None = None


class SessionsListResponse(BaseModel):
    """``GET /admin/auth/sessions`` payload."""

    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionEntry]


async def fetch_user_roles(conn: asyncpg.Connection, username: str) -> list[str]:
    """Return role names assigned to a DB user."""
    rows = await conn.fetch(
        """
        SELECT r.name
          FROM theeyebeta.admin_users u
          JOIN theeyebeta.admin_user_roles ur ON ur.user_id = u.id
          JOIN theeyebeta.admin_roles r ON r.id = ur.role_id
         WHERE u.username = $1 AND u.is_active
        """,
        username,
    )
    return [str(row["name"]) for row in rows]


async def verify_db_credentials(
    conn: asyncpg.Connection,
    username: str,
    password: str,
) -> list[str] | None:
    """Verify username/password against admin_users; return roles or None."""
    row = await conn.fetchrow(
        """
        SELECT password_bcrypt
          FROM theeyebeta.admin_users
         WHERE username = $1 AND is_active
        """,
        username,
    )
    if row is None:
        return None
    try:
        ok = bcrypt.checkpw(password.encode(), row["password_bcrypt"].encode())
    except ValueError:
        return None
    if not ok:
        return None
    return await fetch_user_roles(conn, username)


def register_auth_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited auth handlers to the shared router."""
    from auth_mfa import register_mfa_routes

    register_mfa_routes()

    @router.post("/login", response_model=LoginResponse)
    @limiter.limit("20/minute")
    async def login(
        request: Request,
        body: LoginRequest,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        conn: DbConn,
    ) -> LoginResponse:
        """Verify operator credentials; issue tokens or MFA challenge."""
        _require_auth_config(settings)
        role = await _authenticate(body.username, body.password, conn)

        mfa_state = await _fetch_mfa_state(conn, body.username)
        is_master = role == Role.MASTER_ADMIN.name
        totp_enabled = bool(mfa_state and mfa_state.get("totp_enabled"))

        if is_master and not totp_enabled:
            enroll_token = _encode_token(
                settings=settings,
                subject=body.username,
                token_type=_TOKEN_TYPE_MFA_ENROLL,
                ttl=timedelta(minutes=settings.mfa_token_minutes),
                role=role,
            )
            log.info("admin_login_mfa_enrollment_required", sub=body.username)
            return LoginResponse(
                mfa_enrollment_required=True,
                enrollment_token=enroll_token,
            )

        if totp_enabled or is_master:
            mfa_token = _encode_token(
                settings=settings,
                subject=body.username,
                token_type=_TOKEN_TYPE_MFA_PENDING,
                ttl=timedelta(minutes=settings.mfa_token_minutes),
                role=role,
            )
            log.info("admin_login_mfa_required", sub=body.username, role=role)
            return LoginResponse(mfa_required=True, mfa_token=mfa_token)

        access, refresh, expires_in = await _issue_tokens(
            settings,
            body.username,
            redis,
            role=role,
            ip=_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
        _set_refresh_cookie(response, refresh, settings)
        log.info("admin_login_ok", sub=body.username, role=role)
        return LoginResponse(access_token=access, expires_in=expires_in, role=role)

    @router.post("/refresh", response_model=RefreshResponse)
    @limiter.limit("20/minute")
    async def refresh_tokens(
        request: Request,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        conn: DbConn,
    ) -> RefreshResponse:
        """Rotate refresh cookie and issue a new access token."""
        _require_auth_config(settings)
        raw_refresh = request.cookies.get(settings.refresh_cookie_name)
        if not raw_refresh:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token missing",
            )
        payload = _decode_refresh_token(raw_refresh, settings)
        jti = str(payload["jti"])
        subject = str(payload["sub"])
        role = str(payload.get("role", DEFAULT_ROLE))

        stored_subject = await consume_refresh_token(redis, jti)
        if stored_subject is None:
            revoked = await revoke_all_sessions(redis, subject)
            await write_audit_log(
                conn,
                actor=f"admin-api:{subject}",
                action="security.refresh_token_reuse",
                entity_type="admin_user",
                entity_id=subject,
                payload={
                    "ip": _client_ip(request),
                    "user_agent": request.headers.get("User-Agent"),
                    "revoked_sessions": revoked,
                },
            )
            log.warning("admin_refresh_token_reuse", sub=subject, revoked=revoked)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected; all sessions revoked",
            )
        if stored_subject != subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token subject mismatch",
            )

        access, new_refresh, expires_in = await _issue_tokens(
            settings,
            subject,
            redis,
            role=role,
            ip=_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
        _set_refresh_cookie(response, new_refresh, settings)
        log.info("admin_token_refreshed", sub=subject, role=role)
        return RefreshResponse(access_token=access, expires_in=expires_in, role=role)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    @limiter.limit("20/minute")
    async def logout(
        request: Request,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
    ) -> Response:
        """Revoke refresh token and clear cookie."""
        raw_refresh = request.cookies.get(settings.refresh_cookie_name)
        if raw_refresh:
            try:
                payload = _decode_refresh_token(raw_refresh, settings)
                await revoke_refresh(redis, str(payload["jti"]), str(payload["sub"]))
                log.info("admin_logout_ok", sub=payload.get("sub"))
            except HTTPException:
                log.info("admin_logout_invalid_refresh_ignored")
        _clear_refresh_cookie(response, settings)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/logout/all", status_code=status.HTTP_204_NO_CONTENT)
    @limiter.limit("10/minute")
    async def logout_all(
        request: Request,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        user: CurrentUser,
    ) -> Response:
        """Revoke all refresh sessions for the authenticated user."""
        count = await revoke_all_sessions(redis, user["sub"])
        _clear_refresh_cookie(response, settings)
        log.info("admin_logout_all", sub=user["sub"], revoked=count)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/sessions", response_model=SessionsListResponse)
    async def list_user_sessions(
        redis: RedisDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> SessionsListResponse:
        """List active sessions for the current user."""
        raw = await list_sessions(redis, user["sub"])
        sessions = [SessionEntry(**entry) for entry in raw]
        return SessionsListResponse(sessions=sessions)

    @router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_session(
        session_id: str,
        redis: RedisDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> Response:
        """Revoke one refresh session by jti."""
        sessions = await list_sessions(redis, user["sub"])
        if not any(s["session_id"] == session_id for s in sessions):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        await revoke_refresh(redis, session_id, user["sub"])
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/me", response_model=CurrentUserResponse)
    async def current_user(user: CurrentUser) -> CurrentUserResponse:
        """Return the authenticated operator identity and role."""
        return CurrentUserResponse(username=user["sub"], role=user.get("role", DEFAULT_ROLE))

    return router


async def _fetch_mfa_state(conn: asyncpg.Connection, username: str) -> dict[str, Any] | None:
    """Return MFA columns when migration 0028 is applied."""
    try:
        row = await conn.fetchrow(
            """
            SELECT totp_enabled, totp_secret
              FROM theeyebeta.admin_users
             WHERE username = $1 AND is_active
            """,
            username,
        )
    except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError):
        return None
    return dict(row) if row else None


def _client_ip(request: Request) -> str | None:
    """Extract client IP from request."""
    return request.client.host if request.client else None


async def _authenticate(
    username: str,
    password: str,
    conn: asyncpg.Connection,
) -> str:
    """Authenticate against DB-backed admin users only."""
    try:
        db_roles = await verify_db_credentials(conn, username, password)
        if db_roles is not None:
            return highest_role(db_roles)
    except asyncpg.UndefinedTableError:
        log.warning("admin_rbac_tables_missing", hint="run db migration 0026_admin_rbac")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


def _require_auth_config(settings: Settings) -> None:
    """Ensure JWT keys are configured."""
    if not settings.jwt_private_pem():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth is not configured (JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_PATH)",
        )


def _reject_non_rs256(token: str) -> None:
    """Reject JWT algorithm confusion attacks."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
        ) from exc
    if header.get("alg") != "RS256":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token algorithm",
        )


def _encode_token(
    *,
    settings: Settings,
    subject: str,
    token_type: str,
    ttl: timedelta,
    role: str = DEFAULT_ROLE,
    jti: str | None = None,
) -> str:
    """Sign an RS256 JWT."""
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + ttl,
        "typ": token_type,
        "role": role,
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(
        payload,
        settings.jwt_private_pem(),
        algorithm="RS256",
    )


def decode_access_token(
    token: str,
    settings: Settings,
    *,
    expected_typ: str = _TOKEN_TYPE_ACCESS,
) -> dict[str, Any]:
    """Verify a JWT and return its claims."""
    _reject_non_rs256(token)
    if not settings.jwt_public_pem():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT verification is not configured",
        )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_pem(),
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    if payload.get("typ") != expected_typ:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return payload


def _decode_refresh_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a refresh JWT."""
    payload = decode_access_token(token, settings, expected_typ=_TOKEN_TYPE_REFRESH)
    jti = payload.get("jti")
    sub = payload.get("sub")
    if not isinstance(jti, str) or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed refresh token",
        )
    return payload


async def _issue_tokens(
    settings: Settings,
    subject: str,
    redis: Redis,
    *,
    role: str = DEFAULT_ROLE,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, int]:
    """Sign tokens and store refresh jti with session metadata."""
    access_ttl = timedelta(minutes=settings.access_token_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_days)
    jti = str(uuid.uuid4())
    access = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_ACCESS,
        ttl=access_ttl,
        role=role,
    )
    refresh = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_REFRESH,
        ttl=refresh_ttl,
        role=role,
        jti=jti,
    )
    ttl_seconds = int(refresh_ttl.total_seconds())
    await store_refresh_session(
        redis,
        jti=jti,
        subject=subject,
        ttl_seconds=ttl_seconds,
        ip=ip,
        user_agent=user_agent,
    )
    return access, refresh, int(access_ttl.total_seconds())


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach httpOnly refresh cookie."""
    max_age = settings.refresh_token_days * 24 * 3600
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Remove refresh cookie on logout."""
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
    )
