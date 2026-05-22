# ADR 0003: LiteLLM as the Unified LLM Gateway

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §5](../architecture.md#5-llm--agent-layer), [docs/agents.md](../agents.md)

---

## Context

theeyebeta calls multiple LLM providers (Anthropic Claude, OpenAI GPT) from several services (agent-runtime, rnd-agent, guard-service prompt classifier). Requirements:

1. **Provider abstraction** — switch models without changing call-site code.
2. **Cost tracking** — per-model token usage logged to `audit_log` for budget control.
3. **Rate limiting** — per-model RPM/TPM limits enforced; bursts queued, not dropped.
4. **Retry / fallback** — if Anthropic is rate-limited, fall back to OpenAI on the same request class.
5. **Observability** — every LLM call is a span in Tempo with prompt hash, model, latency, tokens.
6. **Prompt caching** — Anthropic prompt caching headers managed centrally.

Calling provider SDKs directly from each service means duplicating all of the above across five code paths.

---

## Decision

We will implement `llm-gateway` as a **thin FastAPI service wrapping LiteLLM**.

- LiteLLM (`litellm` Python package) provides a unified `completion()` / `acompletion()` interface across 100+ providers with the OpenAI API shape.
- `llm-gateway` adds: authentication (internal bearer token), per-model rate limiting (Redis token bucket), cost logging to `audit_log`, and OTel span emission.
- All other services call `llm-gateway` via `httpx` — they never import provider SDKs directly.

---

## Consequences

### Positive
- Single place to rotate API keys, change models, add/remove providers.
- Retry logic, fallback chains, and timeout policies defined once in `llm-gateway/settings.py`.
- Model aliases (`fast-classifier`, `research-deep`) decouple call sites from concrete model names — change the alias target without touching any caller.
- LiteLLM's `acompletion()` is asyncio-native; no thread-pool workarounds needed.
- Built-in token counting and cost estimation before and after each call.

### Negative
- Additional network hop (localhost HTTP) adds ~1 ms latency per call. Acceptable for LLM calls that take 500 ms–30 s.
- LiteLLM is a fast-moving open-source library; breaking changes occur between minor versions. Pin explicitly; run `uv lock --upgrade` deliberately.
- Structured output (Anthropic `tool_use`, OpenAI `response_format`) requires LiteLLM version alignment with provider API versions.

### Neutral
- `llm-gateway` becomes a shared dependency of nearly every service. Its availability is critical — circuit breaker pattern recommended.
- Streaming responses (`stream=True`) are proxied via chunked HTTP. Services that need streaming must handle `text/event-stream`.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Direct Anthropic SDK in each service** | Duplicates rate limiting, key management, retry logic, cost tracking across N services |
| **Direct OpenAI SDK in each service** | Same problem; adds provider lock-in at the call site |
| **Custom proxy (hand-written)** | LiteLLM already solves provider abstraction; building a custom proxy is undifferentiated work |
| **Portkey / Helicone (SaaS)** | Vendor dependency for a core capability; adds egress latency; cost; data leaves the host |
| **LangChain** | Too heavy; opinionated chain abstractions conflict with our direct `std::expected`-style result handling |

---

## References

- [LiteLLM documentation](https://docs.litellm.ai/)
- [docs/agents.md — llm-gateway section](../agents.md#llm-gateway)
- [docs/architecture.md §5](../architecture.md#5-llm--agent-layer)
