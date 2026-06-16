"""Security tests for JWT verification and auth hardening."""

from __future__ import annotations

import sys
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from auth import decode_access_token  # noqa: E402
from settings import Settings  # noqa: E402


@pytest.fixture
def jwt_settings() -> Settings:
    """Settings with ephemeral RS256 key pair for tests."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return Settings.model_construct(
        jwt_private_key=private_pem,
        jwt_public_key=public_pem,
        jwt_issuer="test-admin",
        admin_password_bcrypt="",
    )


@pytest.mark.unit
def test_rejects_hs256_algorithm_confusion(jwt_settings: Settings) -> None:
    """Tokens with alg != RS256 must be rejected before decode."""
    token = jwt.encode(
        {
            "sub": "attacker",
            "iss": jwt_settings.jwt_issuer,
            "typ": "access",
            "role": "MASTER_ADMIN",
        },
        "symmetric-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token, jwt_settings)
    assert exc_info.value.status_code == 401
    assert "algorithm" in str(exc_info.value.detail).lower()


@pytest.mark.unit
def test_accepts_valid_rs256_access_token(jwt_settings: Settings) -> None:
    """Valid RS256 access tokens decode successfully."""
    from datetime import UTC, datetime, timedelta

    private_pem = jwt_settings.jwt_private_pem()
    now = datetime.now(tz=UTC)
    token = jwt.encode(
        {
            "sub": "operator",
            "iss": jwt_settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "typ": "access",
            "role": "OPERATOR",
        },
        private_pem,
        algorithm="RS256",
    )
    payload = decode_access_token(token, jwt_settings)
    assert payload["sub"] == "operator"
    assert payload["role"] == "OPERATOR"
