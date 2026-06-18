# LLM & Agent Architecture

> See [architecture.md §5](architecture.md#5-llm--agent-layer) for where this fits in the system.

## Overview

The trading-agent "AI staff" is a reports-to hierarchy defined declaratively in
`config/agents/hierarchy.yaml`, rooted at `master-orchestrator` (reports to the human operator,
`reports_to: null`). Eight departments, each with a `<dept>-lead` reporting directly to
`master-orchestrator`, and specialist leaves reporting to their department lead:

| Department | Lead | Reports to |
|------------|------|------------|
| `top` | `master-orchestrator` | human operator |
| `markets` | `markets-lead` | `master-orchestrator` |
| `compliance` | `compliance-lead` | `master-orchestrator` |
| `quant` | `quant-lead` | `master-orchestrator` |
| `macro` | `macro-lead`* | `master-orchestrator` |
| `fundamental` | (lead per `hierarchy.yaml`) | `master-orchestrator` |
| `risk` | (lead per `hierarchy.yaml`) | `master-orchestrator` |
| `audit` | (lead per `hierarchy.yaml`) | `master-orchestrator` |

\* don't hand-maintain the full leaf list here — `config/agents/hierarchy.yaml` is the source of
truth and changes whenever an agent is added/removed; read it directly rather than trusting a
copy in this doc.

Each agent entry carries `reports_to`, `department`, `role`, `constitution_path` (a markdown file
under `agents/<department>/`), `model_default`, and `model_fallback`. The `theeyebeta.agents` table
(migration `0004`, `reports_to` self-FK added in `0033`) is the runtime mirror of this file, kept
in sync by `db/seeds/agents.py` / `db/seeds/agent_hierarchy.py`.

## Model routing — OpenAI only

All agents route through the **LiteLLM proxy** (`config/litellm.yaml`), which exposes two model
aliases, both OpenAI: `gpt-4o-mini` and `gpt-5`. The proxy is the `llm-gateway` docker-compose
service (`:4000`). Migration `0035` explicitly retired the Claude model aliases
(`claude-sonnet-4-6`, `claude-haiku-4-5`) from the `agents` table, replacing them with
`gpt-4o-mini` — there is no Anthropic dependency left in the runtime path.

**Do not confuse this with Claude Code.** Claude Code (this assistant) is a *development* tool
used to write and review code in this repo; it has no role in the live trading-agent pipeline.
`CLAUDE.md` governs how Claude Code should behave as a contributor — it says nothing about the
trading agents described in this file, and vice versa.

## Agent runtime services

| Service | Role | Deployment status |
|---------|------|--------------------|
| `agent_runtime` | Executes agent decision loops; consumes NATS market data | **deployed** (systemd, `:8004`) — see `architecture.md §3.1` |
| `rnd_agent` | Slow-loop research agent — reads snapshots, runs backtests, drafts proposals via the LLM gateway | code-complete, not deployed |
| `guard_service` | Pre-trade signal validation (position limits, daily loss limits, symbol allow/deny list, market hours, circuit breaker) before a signal reaches `master_orchestrator` | code-complete, not deployed |
| `llm_gateway` (dir) | Config/scripts for the LiteLLM proxy — the running proxy itself is the `llm-gateway` container, not a FastAPI app in this directory | n/a |

A signal that fails a `guard_service` rule is rejected with a structured reason code, recorded via
the `guard_violations` table (migration `0005`, resolution tracking added in `0017`).

## Memory & retrieval

`agent_memory` (migration `0004`) stores per-agent embeddings (`vector(1536)`, HNSW index) for
retrieval-augmented context. `news_embeddings` (migration `0003`) does the same for ingested news
articles.

## Reporting chain

`agent_reports` (migration `0033`) stores operator-facing briefings/escalations/rollups/trade
syntheses produced as agents roll results up the `reports_to` chain. The `theeye-reporting-chain`
timer (`deploy/systemd/`) drives this in production.
