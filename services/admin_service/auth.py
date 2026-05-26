"""JWT authentication routes for admin-service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
import structlog
from deps import RedisDep, SettingsDep
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from settings import Settings
from slowapi import Limiter

log = structlog.get_logger()

router = APIRouter(tags=["auth"])


async def get_current_user(request: Request) -> dict[str, str]:
    """Validate Bearer access JWT and return ``{sub: username}``."""
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
    return {"sub": sub}


CurrentUser = Annotated[dict[str, str], Depends(get_current_user)]

_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"
_REFRESH_REDIS_PREFIX = "admin:refresh:"


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


class RefreshResponse(BaseModel):
    """Rotated access token."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


def register_auth_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited auth handlers to the shared router."""

    @router.post("/login", response_model=TokenResponse)
    @limiter.limit("20/minute")
    async def login(
        request: Request,
        body: LoginRequest,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
    ) -> TokenResponse:
        """Verify operator credentials and issue access + refresh tokens."""
        _require_auth_config(settings)
        _verify_password(
            body.password,
            settings.admin_password_bcrypt,
            body.username,
            settings.admin_username,
        )
        access, refresh, expires_in = await _issue_tokens(settings, settings.admin_username, redis)
        _set_refresh_cookie(response, refresh, settings)
        log.info("admin_login_ok", sub=settings.admin_username)
        return TokenResponse(access_token=access, expires_in=expires_in)

    @router.post("/refresh", response_model=RefreshResponse)
    @limiter.limit("20/minute")
    async def refresh_tokens(
        request: Request,
        response: Response,
        settings: SettingsDep,
        redis: RedisDep,
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
        access, new_refresh, expires_in = await _issue_tokens(settings, subject, redis)
        _set_refresh_cookie(response, new_refresh, settings)
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


async def _issue_tokens(
    settings: Settings,
    subject: str,
    redis: Redis,
) -> tuple[str, str, int]:
    """Sign tokens and store refresh jti."""
    access_ttl = timedelta(minutes=settings.access_token_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_days)
    jti = str(uuid.uuid4())
    access = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_ACCESS,
        ttl=access_ttl,
    )
    refresh = _encode_token(
        settings=settings,
        subject=subject,
        token_type=_TOKEN_TYPE_REFRESH,
        ttl=refresh_ttl,
        jti=jti,
    )
    await _store_refresh(redis, jti, subject, int(refresh_ttl.total_seconds()))
    return access, refresh, int(access_ttl.total_seconds())
