# ADR 0007: Three-Model LLM Allocation (Haiku / Sonnet / GPT-5)

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §5](../architecture.md#5-llm--agent-layer), [docs/agents.md](../agents.md), [ADR 0003](0003-litellm-gateway.md)

---

## Context

theeyebeta uses LLMs for qualitatively different tasks with very different latency, cost, and capability requirements:

| Task class | Example | Latency budget | Quality requirement |
|------------|---------|---------------|---------------------|
| **Fast classifier** | Signal intent classification in guard-service | < 200 ms | Binary yes/no; low complexity |
| **Agentic reasoning** | agent-runtime generating a trade signal from market context | 500 ms–2 s | Structured JSON; moderate complexity |
| **Deep research** | rnd-agent synthesising a multi-day research proposal | 10–60 s | Long-form; high reasoning depth |

A single model cannot optimise all three simultaneously without either paying for research-grade compute on every classifier call or accepting degraded quality on deep research.

Part 6.2 of the architecture document defines the allocation.

---

## Decision

We allocate three models, each mapped to a named alias in `llm-gateway`:

| Alias | Model | Used for |
|-------|-------|---------|
| `fast-classifier` | **Claude Haiku 3** | Guard-service intent classification, signal tagging, short summarisation |
| `agent-default` | **Claude Sonnet 4** | agent-runtime signal generation, rnd-agent proposal drafts, structured-output tasks |
| `research-deep` | **OpenAI GPT-5** | rnd-agent deep multi-step analysis, hypothesis generation, backtest-result interpretation |

Call sites use the alias, not the concrete model name. Swapping a model means updating `llm-gateway/settings.py`, not touching callers.

---

## Consequences

### Positive
- **Cost control**: Haiku costs ~20× less per token than Sonnet. Routing every classifier call through Haiku rather than Sonnet is material at trading-platform call volumes.
- **Latency control**: Haiku p50 latency is < 150 ms; Sonnet is 400–800 ms. Fast-path guard checks cannot block on a Sonnet call.
- **Capability alignment**: GPT-5's stronger long-context reasoning outperforms Sonnet on multi-document synthesis (the rnd-agent use case) based on internal evals.
- **Provider redundancy**: Mixing Anthropic and OpenAI means a single provider outage degrades but does not eliminate capability.
- **Alias indirection**: Adding Claude Opus 5 or GPT-5o mini as alternatives requires no call-site changes.

### Negative
- Two providers means two API keys, two billing accounts, two rate-limit surfaces to monitor.
- Prompt engineering must account for model-specific quirks (Anthropic tool_use format vs OpenAI function_call format). LiteLLM normalises these, but edge cases exist.
- GPT-5 pricing is higher than Sonnet for equivalent token counts. rnd-agent calls must be metered and capped.
- Model capability and pricing change frequently (providers release new versions, deprecate old ones). Alias mapping must be reviewed quarterly.

### Neutral
- Model aliases are string constants in `services/llm-gateway/src/llm_gateway/settings.py`. Updating them is a one-line change + redeploy.
- Per-alias token budget limits (TPM caps) are enforced in Redis by llm-gateway. Breached limits return 429 to callers, which retry with exponential backoff.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Single model for everything (Sonnet)** | Over-pays for classifier calls; Sonnet latency too high for guard-service fast path |
| **Single model (GPT-5 only)** | Higher cost; single provider; weaker tool_use ergonomics for structured output compared to Anthropic |
| **Local models (Ollama / llama.cpp)** | Mac mini M2 Pro can run 7 B models; quality insufficient for research tasks; RAM pressure from running alongside all other services |
| **Four-model split** | Marginal benefit does not justify additional alias management overhead at current scale |

---

## References

- [docs/architecture.md §5](../architecture.md#5-llm--agent-layer)
- [docs/agents.md](../agents.md)
- [ADR 0003 — LiteLLM gateway](0003-litellm-gateway.md)
- [Anthropic model pricing](https://www.anthropic.com/pricing)
- [OpenAI model pricing](https://openai.com/pricing)
