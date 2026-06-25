"""One-time live approval token helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta


def mint_approval_token(*, ttl_minutes: int = 15) -> tuple[str, str, datetime]:
    """Return (plaintext token, sha256 hex hash, expiry)."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=ttl_minutes)
    return token, token_hash, expires_at


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
