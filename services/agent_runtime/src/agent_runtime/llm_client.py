"""OpenAI async LLM client with per-call cost tracking."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

# Per-million-token USD prices. Verify against OpenAI's current pricing page.
PRICING_USD_PER_M = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
}

_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class LLMResult:
    """Result of a single LLM chat completion."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int


class LLMClient:
    """Thin wrapper around the OpenAI async Chat Completions API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Send one user message and return the assistant text plus usage stats.

        Args:
            model: OpenAI model identifier (e.g. ``gpt-4o-mini``).
            system: System prompt (constitution body).
            user: User message (snapshot JSON).
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0.0 for deterministic output).

        Returns:
            :class:`LLMResult` with text, token counts, cost, and latency.
        """
        t0 = time.perf_counter()
        msg = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        dt_ms = int((time.perf_counter() - t0) * 1000)
        text = msg.choices[0].message.content or ""
        u = msg.usage
        inp = u.prompt_tokens if u else 0
        out = u.completion_tokens if u else 0
        p = PRICING_USD_PER_M.get(model, PRICING_USD_PER_M[_DEFAULT_MODEL])
        cost = (inp * p["input"] + out * p["output"]) / 1_000_000
        return LLMResult(
            text=text,
            model=msg.model or model,
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=cost,
            latency_ms=dt_ms,
        )
