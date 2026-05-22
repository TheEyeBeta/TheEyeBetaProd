# LLM & Agent Architecture

> **Status:** Stub — expand as agent services are implemented.
> See [architecture.md §5](architecture.md#5-llm--agent-layer).

## Overview

theeyebeta uses three LLM-assisted agent services:

| Service | Role |
|---------|------|
| `agent-runtime` | Executes fast-loop trading signals; consumes live market data from NATS |
| `rnd-agent` | Research agent; generates trading proposals from snapshots + backtests |
| `llm-gateway` | Unified proxy to Anthropic (Claude) and OpenAI; rate-limiting, logging, cost tracking |

## llm-gateway

- Routes requests to Anthropic or OpenAI based on model name
- Enforces per-model rate limits in Redis
- Logs all requests/responses to `audit_log` (excluding PII)
- Returns `std::expected`-style error envelopes for all non-2xx responses

## agent-runtime

- Subscribes to `market.tick.*` and `market.ohlcv.*` NATS subjects
- Runs registered signal strategies (Python + optional C++ hot path)
- Submits signals to `guard-service` before routing onward
- Uses `opentelemetry-instrumentation-fastapi` for trace context propagation

## guard-service

Rules evaluated on every signal before it reaches `master-orchestrator`:

1. Position limit check (against current positions in PostgreSQL)
2. Daily loss limit check
3. Symbol whitelist / blacklist
4. Market hours check
5. Circuit breaker state (Redis flag set by risk-service)

A signal that fails any rule is rejected with a structured reason code written to `audit_log`.

## rnd-agent

Slow-loop research workflow:

1. Reads parquet snapshots from MinIO
2. Runs backtest via `backtest-engine` HTTP API
3. Constructs a structured prompt for `llm-gateway`
4. Parses the LLM response into a `Proposal` Pydantic model
5. Submits to `master-orchestrator` for human or automated approval

## Prompt Templates

_Location:_ `services/rnd-agent/src/rnd_agent/prompts/`

Templates use Jinja2 with typed context objects — no f-string prompt construction.
All prompts are versioned by filename (e.g. `v2_research_proposal.j2`).

## Guard Rules

_Location:_ `services/guard-service/src/guard_service/rules/`

Each rule is a pure function `(Signal, Context) -> Result[Signal, RuleViolation]`.
Rules are composable and independently testable.
