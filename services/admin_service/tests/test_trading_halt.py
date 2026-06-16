"""Unit tests for admin trading emergency halt."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


class _InMemoryRedisStub:
    """Tiny async Redis lookalike for auth and ops clients."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:  # noqa: ARG002
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    async def aclose(self) -> None:
        self._store.clear()


class _RecordingNats:
    """In-memory NATS stub that records published messages."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))

    async def drain(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def _init_trading_test_resources(settings: object) -> None:
    import deps  # noqa: PLC0415

    deps._pool = None
    deps._nats = _RecordingNats()  # noqa: SLF001
    deps._redis = _InMemoryRedisStub()  # noqa: SLF001
    deps._redis_ops = _InMemoryRedisStub()  # noqa: SLF001


async def _close_trading_test_resources() -> None:
    import deps  # noqa: PLC0415

    deps._nats = None
    if deps._redis is not None:
        await deps._redis.aclose()
        deps._redis = None
    if deps._redis_ops is not None:
        await deps._redis_ops.aclose()
        deps._redis_ops = None


async def _mock_db() -> AsyncIterator[AsyncMock]:
    yield AsyncMock()


@pytest.fixture
async def trading_halt_client() -> AsyncIterator[tuple[AsyncClient, _InMemoryRedisStub]]:
    """HTTP client with MASTER_ADMIN role and in-memory ops Redis (no Postgres)."""
    from deps import bind_app_state, get_db  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from rbac import get_authenticated_user  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(
        database_url="postgresql://test:test@localhost/db",
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        redis_ops_url="redis://127.0.0.1:6379/0",
        admin_password_bcrypt="",
        jwt_private_key="",
        jwt_public_key="",
    )

    with (
        patch("deps.init_resources", _init_trading_test_resources),
        patch("deps.close_resources", _close_trading_test_resources),
        patch("api.trading.write_audit_log", AsyncMock()),
    ):
        app = create_app(settings)
        await _init_trading_test_resources(settings)
        bind_app_state(app, settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "test-operator", "role": "MASTER_ADMIN"}

        app.dependency_overrides[get_authenticated_user] = _fake_user
        app.dependency_overrides[get_db] = _mock_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            import deps  # noqa: PLC0415

            ops_stub = deps._redis_ops
            assert isinstance(ops_stub, _InMemoryRedisStub)
            yield client, ops_stub
        app.dependency_overrides.clear()
        await _close_trading_test_resources()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emergency_halt_writes_ops_redis_key(
    trading_halt_client: tuple[AsyncClient, _InMemoryRedisStub],
) -> None:
    """Emergency halt sets oms:submissions_paused:emergency on ops Redis (DB 0)."""
    client, ops_redis = trading_halt_client
    resp = await client.post(
        "/admin/trading/emergency-halt",
        headers={"Authorization": "Bearer test"},
        json={
            "reason": "test halt",
            "consequences_acknowledged": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["halted"] is True
    assert body["redis_paused"] is True

    value = await ops_redis.get("oms:submissions_paused:emergency")
    assert value == "1"
