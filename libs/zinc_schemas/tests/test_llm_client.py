"""Unit tests for :mod:`zinc_schemas.llm_client` (mocked LiteLLM + DB)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from zinc_schemas.llm_client import LLMClient

_PROXY_URL = "http://llm-gateway:4000"
_DB_URL = "postgresql://theeyebeta:test@localhost:5432/theeyebeta"
_VIRTUAL_KEY = "sk-test-virtual-key"


def _completion_payload(
    *,
    model: str = "claude-haiku-4-5",
    content: str = '{"ok": true}',
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cached_tokens: int = 5,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        },
    }


@pytest.fixture
def mock_pg() -> tuple[AsyncMock, AsyncMock]:
    """Mock ``await AsyncConnection.connect()`` → connection with execute/commit."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    connect = AsyncMock(return_value=cm)
    return connect, conn


@pytest.mark.unit
async def test_chat_returns_parsed_json_and_usage(
    httpx_mock,
    mock_pg: tuple[AsyncMock, AsyncMock],
) -> None:
    """Structured output is parsed; usage and cost headers are captured."""
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        json=_completion_payload(model="gpt-5", content='{"signal": "buy"}'),
        headers={"x-litellm-response-cost": "0.0042"},
    )
    connect, _conn = mock_pg
    client = LLMClient(_VIRTUAL_KEY, _PROXY_URL, database_url=_DB_URL)
    with patch("zinc_schemas.llm_client.psycopg.AsyncConnection.connect", connect):
        result = await client.chat(
            "gpt-5",
            [{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )

    assert result.content == {"signal": "buy"}
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 20
    assert result.usage.cache_read == 5
    assert result.cost_usd == pytest.approx(0.0042)
    assert result.model_used == "gpt-5"
    assert result.latency_ms >= 0
    await client.aclose()


@pytest.mark.unit
async def test_chat_inserts_model_runs_row(
    httpx_mock,
    mock_pg: tuple[AsyncMock, AsyncMock],
) -> None:
    """Every successful call inserts exactly one model_runs row."""
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        json=_completion_payload(),
        headers={"x-litellm-response-cost": "0.001"},
    )
    run_id = uuid4()
    client = LLMClient(
        _VIRTUAL_KEY,
        _PROXY_URL,
        database_url=_DB_URL,
        run_id=run_id,
    )

    connect, conn = mock_pg
    with patch("zinc_schemas.llm_client.psycopg.AsyncConnection.connect", connect):
        await client.chat(
            "claude-haiku-4-5",
            [{"role": "user", "content": "classify"}],
            prompt_cache_key="guard-v1",
            max_tokens=64,
            temperature=0.0,
        )

    conn.execute.assert_called_once()
    sql, params = conn.execute.call_args[0]
    assert "INSERT INTO theeyebeta.model_runs" in sql
    assert params[0] == run_id
    assert params[1] == "anthropic"
    assert params[2] == "claude-haiku-4-5"
    assert params[3] == "completion"
    assert params[4] == 100
    assert params[5] == 20
    assert params[6] == 5
    assert params[7] == 0
    assert params[8] == pytest.approx(0.001)
    assert params[10] == "ok"
    conn.commit.assert_called_once()
    await client.aclose()


@pytest.mark.unit
async def test_chat_retries_transient_errors(
    httpx_mock,
    mock_pg: tuple[AsyncMock, AsyncMock],
) -> None:
    """429 responses are retried up to three attempts."""
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        status_code=429,
    )
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        status_code=429,
    )
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        json=_completion_payload(),
        headers={"x-litellm-response-cost": "0.0005"},
    )
    client = LLMClient(_VIRTUAL_KEY, _PROXY_URL, database_url=_DB_URL)

    connect, _conn = mock_pg
    with patch("zinc_schemas.llm_client.psycopg.AsyncConnection.connect", connect):
        result = await client.chat("claude-haiku-4-5", [{"role": "user", "content": "x"}])

    assert result.model_used == "claude-haiku-4-5"
    assert len(httpx_mock.get_requests()) == 3
    await client.aclose()


@pytest.mark.unit
async def test_chat_records_error_row_on_failure(
    httpx_mock,
    mock_pg: tuple[AsyncMock, AsyncMock],
) -> None:
    """Failed calls still persist a model_runs row with status error."""
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        status_code=400,
        json={"error": "bad request"},
    )
    client = LLMClient(_VIRTUAL_KEY, _PROXY_URL, database_url=_DB_URL)

    connect, conn = mock_pg
    with (
        patch("zinc_schemas.llm_client.psycopg.AsyncConnection.connect", connect),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await client.chat("gpt-5", [{"role": "user", "content": "x"}])

    _sql, params = conn.execute.call_args[0]
    assert params[10] == "error"
    assert params[4] == 0
    await client.aclose()


@pytest.mark.unit
async def test_chat_authorization_header(
    httpx_mock,
    mock_pg: tuple[AsyncMock, AsyncMock],
) -> None:
    """Virtual key is sent as Bearer token."""
    httpx_mock.add_response(
        url=f"{_PROXY_URL}/v1/chat/completions",
        json=_completion_payload(content="plain text"),
    )
    client = LLMClient(_VIRTUAL_KEY, _PROXY_URL, database_url=_DB_URL)

    connect, _conn = mock_pg
    with patch("zinc_schemas.llm_client.psycopg.AsyncConnection.connect", connect):
        result = await client.chat(
            "claude-haiku-4-5",
            [{"role": "user", "content": "hi"}],
        )

    request = httpx_mock.get_requests()[0]
    assert request.headers["authorization"] == f"Bearer {_VIRTUAL_KEY}"
    assert result.content == "plain text"
    await client.aclose()
