"""JWT authentication routes for admin-service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote

import bcrypt
import jwt
import structlog
from deps import DbConn, RedisDep, SettingsDep
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from settings import Settings
from slowapi import Limiter

log = structlog.get_logger()

router = APIRouter(tags=["auth"])


async def get_current_user(request: Request) -> dict[str, str]:
    """Validate Bearer access JWT (header or access cookie) and return claims."""
    settings: Settings = request.app.state.settings
    token = _extract_access_token(request, settings)
    if not token:
        if _should_redirect_to_login(request):
            next_path = f"{request.url.path}{'?' + request.url.query if request.url.query else ''}"
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/admin/login?next={quote(next_path, safe='')}"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(token, settings)
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )
    roles_raw = payload.get("roles")
    roles: list[str]
    if isinstance(roles_raw, str) and roles_raw:
        roles = [roles_raw]
    elif isinstance(roles_raw, list):
        roles = [str(r) for r in roles_raw if r]
    else:
        roles = ["operator"]
    return {"sub": sub, "roles": roles}


CurrentUser = Annotated[dict[str, str], Depends(get_current_user)]

_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"
_TOKEN_TYPE_MFA_CHALLENGE = "mfa_challenge"
_MFA_CHALLENGE_TTL_MINUTES = 5
_REFRESH_REDIS_PREFIX = "admin:refresh:"


def _extract_access_token(request: Request, settings: Settings) -> str | None:
    """Read access JWT from Authorization header or browser cookie."""
    authorization = request.headers.get("Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    cookie = request.cookies.get(settings.access_cookie_name)
    return cookie.strip() if cookie else None


def _should_redirect_to_login(request: Request) -> bool:
    """Browser page loads should redirect; API/htmx should receive 401 JSON."""
    if request.headers.get("HX-Request"):
        return False
    if request.method not in {"GET", "HEAD"}:
        return False
    path = request.url.path
    if path in {"/admin/login", "/admin/health"}:
        return False
    if path.startswith(("/admin/auth", "/admin/static")):
        return False
    accept = request.headers.get("accept", "").lower()
    if "text/html" in accept:
        return True
    return request.headers.get("sec-fetch-dest") == "document"


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


class LoginResponse(BaseModel):
    """``/login`` result: either tokens, or an MFA challenge to complete."""

    model_config = ConfigDict(extra="forbid")

    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    mfa_required: bool = False
    challenge_token: str | None = None


class MfaVerifyRequest(BaseModel):
    """Body for completing a password login that required an MFA code."""

    model_config = ConfigDict(extra="forbid")

    challenge_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class RefreshResponse(BaseModel):
    """Rotated access token."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


def register_auth_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited auth handlers to the shared router."""

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
        """Verify operator credentials; issue tokens or an MFA challenge."""
        _require_auth_config(settings)
        user_id, subject, roles, mfa_enabled, totp_secret = await _authenticate(
            conn,
            settings,
            body.username,
            body.password,
        )
        if mfa_enabled and totp_secret:
            challenge_token = _encode_token(
                settings=settings,
                subject=subject,
                token_type=_TOKEN_TYPE_MFA_CHALLENGE,
                ttl=timedelta(minutes=_MFA_CHALLENGE_TTL_MINUTES),
            )
            log.info("admin_login_mfa_required", sub=subject)
            return LoginResponse(mfa_required=True, challenge_token=challenge_token)
        access, expires_in = await _complete_login(
            request,
            response,
            settings,
            redis,
            conn,
            user_id=user_id,
            subject=subject,
            roles=roles,
        )
        return LoginResponse(access_token=access, expires_in=expires_in)

    @router.post("/mfa/verify", response_model=LoginResponse)
    @limiter.limit("10/minute")
    async def verify_mfa(
        request: Request,
        body: MfaVerifyRequest,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
        conn: DbConn,
    ) -> LoginResponse:
        """Complete a login that required an MFA code."""
        import pyotp

        _require_auth_config(settings)
        payload = _decode_mfa_challenge_token(body.challenge_token, settings)
        subject = str(payload["sub"])

        from users import repository as users_repo

        row = await users_repo.get_user_by_username(conn, subject)
        if row is None or not row["totp_secret"] or not row["mfa_enabled"]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA not enrolled")
        if not pyotp.TOTP(str(row["totp_secret"])).verify(body.code, valid_window=1):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
        roles = await users_repo.get_user_roles(conn, row["id"])
        access, expires_in = await _complete_login(
            request,
            response,
            settings,
            redis,
            conn,
            user_id=row["id"],
            subject=subject,
            roles=roles,
        )
        log.info("admin_mfa_verify_ok", sub=subject)
        return LoginResponse(access_token=access, expires_in=expires_in)

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
        if not await _refresh_active(redis, jti, subject):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token revoked or expired",
            )
        await _revoke_refresh(redis, jti)
        roles = await _roles_for_subject(conn, settings, subject)
        access, new_refresh, expires_in, _ = await _issue_tokens(
            settings,
            subject,
            roles,
            redis,
        )
        _set_refresh_cookie(response, new_refresh, settings)
        _set_access_cookie(response, access, settings)
        log.info("admin_token_refreshed", sub=subject)
        return RefreshResponse(access_token=access, expires_in=expires_in)

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
                await _revoke_refresh(redis, str(payload["jti"]))
                log.info("admin_logout_ok", sub=payload.get("sub"))
            except HTTPException:
                log.info("admin_logout_invalid_refresh_ignored")
        _clear_refresh_cookie(response, settings)
        _clear_access_cookie(response, settings)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def _require_auth_config(settings: Settings) -> None:
    """Ensure JWT keys and admin password hash are configured."""
    if not settings.admin_password_bcrypt or not settings.jwt_private_pem():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth is not configured (ADMIN_PASSWORD_BCRYPT / JWT_PRIVATE_KEY)",
        )


def _verify_password(password: str, password_hash: str, username: str, expected: str) -> None:
    """Check bcrypt password; respond with generic 401 on failure."""
    if username != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    try:
        ok = bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError as exc:
        log.error("admin_bcrypt_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth misconfigured",
        ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )


def _encode_token(
    *,
    settings: Settings,
    subject: str,
    token_type: str,
    ttl: timedelta,
    jti: str | None = None,
    roles: list[str] | None = None,
) -> str:
    """Sign an RS256 JWT."""
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + ttl,
        "typ": token_type,
    }
    if jti is not None:
        payload["jti"] = jti
    if roles:
        payload["roles"] = roles
    return jwt.encode(
        payload,
        settings.jwt_private_pem(),
        algorithm="RS256",
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify an access JWT and return its claims.

    Raises:
        HTTPException: 401 when verification fails.
    """
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
    if payload.get("typ") != _TOKEN_TYPE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return payload


def _decode_refresh_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a refresh JWT."""
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
            detail="Invalid or expired refresh token",
        ) from exc
    if payload.get("typ") != _TOKEN_TYPE_REFRESH:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token type",
        )
    jti = payload.get("jti")
    sub = payload.get("sub")
    if not isinstance(jti, str) or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed refresh token",
        )
    return payload


def _decode_mfa_challenge_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify the short-lived challenge JWT issued by ``/login`` when MFA is required."""
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
            detail="Invalid or expired MFA challenge",
        ) from exc
    if payload.get("typ") != _TOKEN_TYPE_MFA_CHALLENGE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid challenge token type",
        )
    return payload


async def _store_refresh(redis: Redis, jti: str, subject: str, ttl_seconds: int) -> None:
    """Persist refresh ``jti`` until expiry (rotation / logout)."""
    key = f"{_REFRESH_REDIS_PREFIX}{jti}"
    await redis.set(key, subject, ex=ttl_seconds)


async def _refresh_active(redis: Redis, jti: str, subject: str) -> bool:
    """Return whether the refresh ``jti`` is still valid for ``subject``."""
    stored = await redis.get(f"{_REFRESH_REDIS_PREFIX}{jti}")
    return stored == subject


async def _revoke_refresh(redis: Redis, jti: str) -> None:
    """Revoke a refresh token by deleting its Redis entry."""
    await redis.delete(f"{_REFRESH_REDIS_PREFIX}{jti}")


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


def _set_access_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach short-lived access cookie for full-page HTML navigation."""
    max_age = settings.access_token_minutes * 60
    response.set_cookie(
        key=settings.access_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path=settings.access_cookie_path,
    )


def _clear_access_cookie(response: Response, settings: Settings) -> None:
    """Remove access cookie on logout."""
    response.delete_cookie(
        key=settings.access_cookie_name,
        path=settings.access_cookie_path,
    )


async def _issue_tokens(
    settings: Settings,
    subject: str,
    roles: list[str],
    redis: Redis,
) -> tuple[str, str, int, str]:
    """Sign tokens and store refresh jti."""
    access_ttl = timedelta(minutes=settings.access_token_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_days)
    jti = str(uuid.uuid4())
    access = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_ACCESS,
        ttl=access_ttl,
        roles=roles,
    )
    refresh = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_REFRESH,
        ttl=refresh_ttl,
        jti=jti,
    )
    await _store_refresh(redis, jti, subject, int(refresh_ttl.total_seconds()))
    return access, refresh, int(access_ttl.total_seconds()), jti


async def _complete_login(
    request: Request,
    response: Response,
    settings: Settings,
    redis: Redis,
    conn: Any,
    *,
    user_id: Any | None,
    subject: str,
    roles: list[str],
) -> tuple[str, int]:
    """Issue tokens, record the session, and set cookies for a successful login."""
    access, refresh, expires_in, jti = await _issue_tokens(settings, subject, roles, redis)
    if user_id is not None:
        from users.service import AdminUsersService

        svc = AdminUsersService(conn, redis=redis)
        await svc.record_session(
            user_id=user_id,
            refresh_jti=jti,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    _set_refresh_cookie(response, refresh, settings)
    _set_access_cookie(response, access, settings)
    log.info("admin_login_ok", sub=subject, roles=roles)
    return access, expires_in


async def _authenticate(
    conn: Any,
    settings: Settings,
    username: str,
    password: str,
) -> tuple[Any | None, str, list[str], bool, str | None]:
    """DB-first auth with env fallback for bootstrap operator.

    Returns ``(user_id, subject, roles, mfa_enabled, totp_secret)``.
    """
    import asyncpg

    from users.service import AdminUsersService

    svc = AdminUsersService(conn, redis=None)
    try:
        user_id, subject, roles, mfa_enabled, totp_secret = await svc.authenticate(
            username,
            password,
        )
        if user_id is not None:
            return user_id, subject, roles, mfa_enabled, totp_secret
    except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError) as exc:
        log.warning("admin_db_auth_schema_missing", error=str(exc))
    _verify_password(
        password,
        settings.admin_password_bcrypt,
        username,
        settings.admin_username,
    )
    return None, settings.admin_username, ["operator", "MASTER_ADMIN"], False, None


async def _roles_for_subject(conn: Any, settings: Settings, subject: str) -> list[str]:
    from users.repository import get_user_by_username, get_user_roles

    row = await get_user_by_username(conn, subject)
    if row is not None:
        return await get_user_roles(conn, row["id"])
    if subject == settings.admin_username:
        return ["operator", "MASTER_ADMIN"]
    return ["operator"]
