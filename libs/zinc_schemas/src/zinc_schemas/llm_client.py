"""Async LiteLLM proxy client with cost tracking and model_runs persistence."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from uuid import UUID

import httpx
import psycopg
import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field
from tenacity import (
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.asyncio import AsyncRetrying

log = structlog.get_logger()
_tracer = trace.get_tracer("zinc_schemas.llm_client")

_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class Usage(BaseModel):
    """Token usage for a single chat completion."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read: int = Field(default=0, description="Tokens read from prompt cache.")
    cache_write: int = Field(default=0, description="Tokens written to prompt cache.")


class ChatResponse(BaseModel):
    """Normalized LiteLLM chat completion result."""

    content: str | dict[str, Any] | list[Any] | None
    usage: Usage
    cost_usd: float
    latency_ms: int
    model_used: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None


def _normalize_pg_url(url: str) -> str:
    """Return a ``postgresql://`` DSN understood by psycopg."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _provider_from_model(model: str) -> str:
    """Map a model identifier to a provider label for ``model_runs``."""
    lower = model.lower()
    if "claude" in lower or "anthropic" in lower:
        return "anthropic"
    if lower.startswith("gpt") or "openai" in lower or "text-embedding" in lower:
        return "openai"
    return "litellm"


def _parse_usage(raw: dict[str, Any] | None) -> Usage:
    """Extract token counts from an OpenAI-compatible usage object."""
    if not raw:
        return Usage()
    details = raw.get("prompt_tokens_details") or {}
    cache_read = int(
        details.get("cached_tokens") or raw.get("cache_read_input_tokens") or 0,
    )
    cache_write = int(raw.get("cache_creation_input_tokens") or 0)
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
        cache_read=cache_read,
        cache_write=cache_write,
    )


def _parse_cost_usd(headers: httpx.Headers, body: dict[str, Any]) -> float:
    """Read cost from LiteLLM response header or usage payload."""
    header_cost = headers.get("x-litellm-response-cost")
    if header_cost is not None:
        try:
            return float(header_cost)
        except ValueError:
            log.warning("litellm_invalid_cost_header", value=header_cost)
    usage = body.get("usage") or {}
    if isinstance(usage, dict) and usage.get("cost") is not None:
        return float(usage["cost"])
    hidden = body.get("_hidden_params") or {}
    if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
        return float(hidden["response_cost"])
    return 0.0


def _parse_content(
    message_content: str | None,
    *,
    response_format: dict[str, Any] | None,
) -> str | dict[str, Any] | list[Any] | None:
    """Return assistant content, parsing JSON when structured output was requested."""
    if message_content is None:
        return None
    if response_format and response_format.get("type") == "json_object":
        try:
            parsed: dict[str, Any] | list[Any] = json.loads(message_content)
            return parsed
        except json.JSONDecodeError:
            log.warning("llm_json_parse_failed", content_preview=message_content[:200])
            return message_content
    return message_content


def _is_retryable(exc: BaseException) -> bool:
    """Return True when the HTTP error is transient."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class LLMClient:
    """Thin async client for the self-hosted LiteLLM proxy."""

    def __init__(
        self,
        virtual_key: str,
        base_url: str = "http://llm-gateway:4000",
        *,
        database_url: str | None = None,
        run_id: UUID | None = None,
        timeout: float = 120.0,
    ) -> None:
        """Configure the client.

        Args:
            virtual_key: LiteLLM virtual key (``Authorization: Bearer``).
            base_url: LiteLLM proxy base URL (no trailing path).
            database_url: Postgres DSN for ``model_runs`` inserts. Falls back to
                ``MODEL_RUNS_DATABASE_URL`` then ``DATABASE_URL``.
            run_id: Optional ``agent_runs.id`` foreign key for correlated runs.
            timeout: HTTP request timeout in seconds.
        """
        self._virtual_key = virtual_key
        self._base_url = base_url.rstrip("/")
        self._run_id = run_id
        raw_dsn = (
            database_url
            or os.environ.get("MODEL_RUNS_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or ""
        )
        self._database_url = _normalize_pg_url(raw_dsn) if raw_dsn else ""
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {virtual_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        response_format: dict[str, Any] | None = None,
        prompt_cache_key: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        tool_choice: str | dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Call ``/v1/chat/completions`` and persist a ``model_runs`` row.

        Args:
            model: LiteLLM model alias (e.g. ``claude-sonnet-4-6``).
            messages: OpenAI-style chat messages.
            response_format: Optional structured output spec (``json_object``, etc.).
            prompt_cache_key: Optional cache key forwarded in request metadata.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            tool_choice: OpenAI tool_choice parameter.
            tools: OpenAI tool definitions for function calling.

        Returns:
            Parsed :class:`ChatResponse` with usage, cost, and resolved model.

        Raises:
            httpx.HTTPError: After retries are exhausted.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if tools is not None:
            body["tools"] = tools
        if prompt_cache_key is not None:
            body.setdefault("metadata", {})["prompt_cache_key"] = prompt_cache_key

        t0 = time.perf_counter()
        status = "error"
        result: ChatResponse | None = None

        with _tracer.start_as_current_span(
            "llm.chat",
            attributes={"llm.model": model, "llm.base_url": self._base_url},
        ) as span:
            try:
                response_data, response_headers = await self._post_with_retry(body)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                result = self._build_chat_response(
                    model,
                    response_data,
                    response_headers,
                    response_format=response_format,
                    latency_ms=latency_ms,
                )
                status = "ok"
                span.set_attribute("llm.model_used", result.model_used)
                span.set_attribute("llm.cost_usd", result.cost_usd)
                span.set_attribute("llm.prompt_tokens", result.usage.prompt_tokens)
                span.set_attribute("llm.completion_tokens", result.usage.completion_tokens)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                await self._record_model_run(
                    model=model if result is None else result.model_used,
                    usage=result.usage if result else Usage(),
                    cost_usd=result.cost_usd if result else 0.0,
                    latency_ms=latency_ms,
                    status=status,
                )

    async def _post_with_retry(self, body: dict[str, Any]) -> tuple[dict[str, Any], httpx.Headers]:
        """POST chat completions with exponential backoff on transient failures."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                response = await self._http.post("/v1/chat/completions", json=body)
                if response.is_error:
                    detail = response.text
                    try:
                        detail = response.json()["error"]["message"]
                    except (ValueError, KeyError, TypeError):
                        pass
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code} from LiteLLM proxy: {detail}",
                        request=response.request,
                        response=response,
                    )
                return response.json(), response.headers
        msg = "chat completion failed without response"
        raise RuntimeError(msg)

    def _build_chat_response(
        self,
        requested_model: str,
        data: dict[str, Any],
        headers: httpx.Headers,
        *,
        response_format: dict[str, Any] | None,
        latency_ms: int,
    ) -> ChatResponse:
        """Map LiteLLM JSON + headers to :class:`ChatResponse`."""
        choices = data.get("choices") or []
        choice0 = choices[0] if choices else {}
        message = choice0.get("message", {})
        raw_content = message.get("content")
        content = _parse_content(raw_content, response_format=response_format)
        usage = _parse_usage(data.get("usage"))
        model_used = str(data.get("model") or requested_model)
        cost_usd = _parse_cost_usd(headers, data)
        tool_calls = message.get("tool_calls") or []
        return ChatResponse(
            content=content,
            usage=usage,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model_used=model_used,
            tool_calls=list(tool_calls) if isinstance(tool_calls, list) else [],
            finish_reason=choice0.get("finish_reason"),
        )

    async def record_tool_run(
        self,
        *,
        tool_name: str,
        latency_ms: int,
        status: str = "ok",
    ) -> None:
        """Insert a tool-call row into ``theeyebeta.model_runs`` (kind=tool_call)."""
        await self._record_model_run(
            model=tool_name,
            usage=Usage(),
            cost_usd=0.0,
            latency_ms=latency_ms,
            status=status,
            kind="tool_call",
            provider="tool",
        )

    async def _record_model_run(
        self,
        *,
        model: str,
        usage: Usage,
        cost_usd: float,
        latency_ms: int,
        status: str,
        kind: str = "completion",
        provider: str | None = None,
    ) -> None:
        """Insert one row into ``theeyebeta.model_runs``."""
        if not self._database_url:
            log.warning("model_runs_skipped", reason="database_url not configured")
            return

        resolved_provider = provider or _provider_from_model(model)
        sql = """
            INSERT INTO theeyebeta.model_runs (
                run_id, provider, model, kind,
                input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens,
                cost_usd, latency_ms, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            self._run_id,
            resolved_provider,
            model,
            kind,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.cache_read,
            usage.cache_write,
            cost_usd,
            latency_ms,
            status,
        )
        try:
            async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
                await conn.execute(sql, params)
                await conn.commit()
            log.debug(
                "model_run_recorded",
                model=model,
                status=status,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        except Exception:
            log.exception("model_run_insert_failed", model=model, status=status)
            raise
