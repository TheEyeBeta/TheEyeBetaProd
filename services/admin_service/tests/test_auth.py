"""Unit tests for admin JWT auth."""

from __future__ import annotations

import sys
from pathlib import Path

import bcrypt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from auth import decode_access_token  # noqa: E402
from main import create_app  # noqa: E402
from settings import Settings  # noqa: E402


def _rsa_pem_pair() -> tuple[str, str]:
    """Generate ephemeral RS256 key pair for tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with in-memory auth configuration."""
    private_pem, public_pem = _rsa_pem_pair()
    password_hash = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_BCRYPT", password_hash)
    monkeypatch.setenv("JWT_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("JWT_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("ADMIN_DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/nodb")
    monkeypatch.setenv("NATS_URL", "nats://127.0.0.1:4222")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    from settings import get_settings  # noqa: E402

    get_settings.cache_clear()
    return get_settings()


@pytest.mark.unit
def test_decode_access_token(test_settings: Settings) -> None:
    """Access tokens round-trip through RS256 verification."""
    from datetime import timedelta  # noqa: E402

    from auth import _encode_token  # noqa: E402

    token = _encode_token(
        settings=test_settings,
        subject="admin",
        token_type="access",
        ttl=timedelta(minutes=15),
    )
    payload = decode_access_token(token, test_settings)
    assert payload["sub"] == "admin"
    assert payload["typ"] == "access"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_login_requires_live_infra(test_settings: Settings) -> None:
    """Login integration needs postgres/nats/redis — skipped in unit CI."""
    pytest.importorskip("asyncpg")
    pytest.skip("Requires running redis/postgres (smoke); see test_login_smoke marker")


@pytest.mark.unit
def test_health_route_builds() -> None:
    """App factory exposes /admin/health without starting lifespan deps."""
    app = create_app()
    paths = [getattr(r, "path", None) for r in app.routes]
    assert "/admin/health" in paths
