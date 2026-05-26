# llm-gateway (LiteLLM proxy)

Self-hosted [LiteLLM](https://docs.litellm.ai/) proxy for theeyebeta. Exposes an OpenAI-compatible API on **port 7020** (container port 4000) with virtual keys, spend limits, routing fallbacks, and audit logging.

## Models (v1)

| Proxy name | Vendor route | Typical use |
|------------|--------------|-------------|
| `claude-sonnet-4-6` | Anthropic Sonnet | agent-runtime executors |
| `claude-haiku-4-5` | Anthropic Haiku | guard-service classifier |
| `gpt-5` | OpenAI GPT | rnd-agent deep research |
| `text-embedding-3-large` | OpenAI embeddings | vector pipelines |

Router fallbacks: sonnet ↔ gpt-5, haiku → sonnet. Cooldown: 30s after 3 failures.

## Prerequisites

1. Postgres migration `0012_litellm_db` (creates `litellm` DB + role).
2. Provider API keys in `.env` or sops secrets.
3. `LITELLM_MASTER_KEY` (must start with `sk-`).

## Local bring-up

```bash
# From repo root — set passwords/keys in .env first
export LITELLM_DB_PASSWORD=changeme_litellm
export LITELLM_MASTER_KEY=sk-theeyebeta-master-dev-change-me
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

make db-migrate   # applies 0012_litellm_db when LITELLM_DB_PASSWORD is set

docker compose up -d postgres redis llm-gateway
```

Health:

```bash
curl -s http://127.0.0.1:7020/health
```

UI: http://127.0.0.1:7020/ui (log in with `LITELLM_MASTER_KEY`).

## Virtual keys

After the proxy is healthy and `DATABASE_URL` is wired:

```bash
export LITELLM_MASTER_KEY=sk-...
python services/llm_gateway/scripts/provision_virtual_keys.py
```

Store printed values in `secrets/prod.enc.yaml`:

- `LITELLM_KEY_AGENT_RUNTIME_EXECUTORS`
- `LITELLM_KEY_RND_AGENT`
- `LITELLM_KEY_GUARD_SERVICE_CLASSIFIER`
- `LITELLM_KEY_EMBEDDINGS`

| Key alias | Budget | Models |
|-----------|--------|--------|
| agent-runtime-executors | $50/day | sonnet, haiku, gpt-5 |
| rnd-agent | $5/day | gpt-5 only |
| guard-service-classifier | $5/day | haiku only |
| embeddings | $2/day | text-embedding-3-large |

## Configuration

- `config.yaml` — model list, router, Redis prompt cache (TTL 300s), audit logs.
- Env vars (see `.env.example`): `LITELLM_DATABASE_URL`, `LITELLM_MASTER_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

## Related

- [ADR 0003](../../docs/adr/0003-litellm-gateway.md)
- [ADR 0007](../../docs/adr/0007-three-model-llm-allocation.md)
