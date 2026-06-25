# Action Items — LLM Backend, Agent System, DataAPI

Compiled 2026-06-25 from a live investigation session. Everything marked **VERIFIED**
was confirmed by reading the actual code/config in this checkout. Everything marked
**NEEDS LIVE CHECK** could not be confirmed because the production box
(`the-eye-beta-server`, Tailscale 100.77.87.18) did not respond to SSH command
execution or to direct HTTP probes on ports 7200/7020 from this machine — see §E.

---

## A. LLM endpoint 500s (all 38 agents) — TheEyeProd

**VERIFIED — not a bug:** The dual-deployment port setup (container port 4000 vs
bare-metal port 7020) is intentional. `services/llm_gateway/config.yaml:1` documents
it, `.env.example:55` sets `LITELLM_PROXY_URL=http://127.0.0.1:7020` for the bare-metal
path, and every client (`llm_client.py`, `agent_runtime/runner.py`,
`master_orchestrator/settings.py`, `guard_service/creative_classifier.py`) reads that
env var before falling back to the Docker hostname. The `infra/systemd/theeyebeta-litellm.service`
unit correctly runs `--port 7020`.

**NEEDS LIVE CHECK** — run these directly on the box:
```bash
systemctl status theeyebeta-litellm
journalctl -u theeyebeta-litellm -n 100      # the actual reason litellm 500s
grep LITELLM_PROXY_URL ~/TheEyeBeta2025/TheEyeBetaProd/.env
curl -s http://127.0.0.1:7020/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```
The journalctl output is the one thing that actually answers "why 500" — common causes
are an invalid/expired `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`, a rejected model name, or
the upstream provider erroring.

**VERIFIED bug, recommended fix** — `libs/zinc_schemas/src/zinc_schemas/llm_client.py:273-274`:
```python
response = await self._http.post("/v1/chat/completions", json=body)
response.raise_for_status()
```
`raise_for_status()` discards litellm's JSON error body. Every agent failure shows a
bare "500 Internal Server Error" with no reason. Fix: catch `httpx.HTTPStatusError`,
pull `response.json()["error"]["message"]` (litellm's standard error shape) into the
raised exception, so the real cause lands in `agent_runs.error` and the OTel span
instead of being thrown away. Low-risk, isolated change — not yet applied, pending
your go-ahead.

**VERIFIED cleanup item** — `config/litellm.yaml` contains a dangerous stale alias
(`claude-sonnet-4-6` → `openai/gpt-4o-mini`) and is not referenced anywhere in code
(grepped, zero hits outside itself). Looks like a leftover from an earlier setup.
Safe to delete to prevent someone accidentally pointing a service at it later.

**Unconfirmed gap** — `agents/top/master-orchestrator.agent.md` defines the
master-orchestrator agent, but `db/seeds/agents.py:35-63` does not insert a row for it
(only `technical-analyst`, `macro-lead`, `news-sentiment` are seeded). Whether this
matters depends on whether `agent_runtime/runner.py` loads agents from the `.agent.md`
file directly or requires a DB row — not confirmed either way. Worth a quick check
before assuming it's fine.

---

## B. Agent success rate (20-33% over 7 days) — TheEyeProd

Blocked on A — every `agent_runs` row currently fails at the LLM call, so "success
rate" right now is really "LLM backend reachability rate," not a signal about
constitution quality. Once A is resolved, the actual constitution-quality audit is:

1. Re-pull `agent_runs` success rate after a few days of real (non-500) traffic.
2. For agents still failing, pull `agent_runs.error` (now populated with the real
   reason, after the fix above) and bucket failures: malformed tool-call output,
   `max_turns` exhausted, JSON schema validation failures on `output_schema_version`,
   timeout vs. logic error.
3. Diff each failing agent's `.agent.md` constitution against ones with high success
   rates in the same department — look for missing `tools`, overly broad
   `permissionMode`, or a `model`/`fallback` pair that doesn't match what's actually
   in `services/llm_gateway/config.yaml`'s `model_list`.
4. Spot-check `temperature=0.0` + `response_format: json_object` calls (used
   everywhere per `runner.py`) against agents whose prompts ask for free-form prose —
   a mismatch there silently produces malformed/truncated JSON the parser rejects.

---

## C. Sector/Universe JSON endpoints — TheEyeProd (code already written, not deployed)

Done this session: `services/admin_service/api/sectors.py` and `api/universe.py` now
return JSON (not just HTML) when `Accept: application/json`, following the same
`prefers_html()` pattern already used elsewhere in this codebase. Syntax- and
import-checked locally; not deployed.

**To ship:** review the diff, commit, push to `main` — `.github/workflows/deploy.yml`
handles the rest (Tailscale CI connection → `git reset --hard origin/main` → `uv sync`
→ `systemctl restart theeyebeta-admin theeyebeta-litellm` → health check). Until that
runs, the Universe Caps/Churn and Sector Rotation/Breadth/Performance pages in the
terminal frontend will still get HTML back from these two routes.

---

## D. Database/SQL console — accepted risk, no action needed

You explicitly approved wiring a read-only SQL input (textarea + Run) against
`/admin/sql/query` in the terminal frontend. Backend already enforces SELECT-only via
keyword filtering (`services/admin_service/api/sql.py`). No outstanding item here —
documented for awareness, not as a TODO.

---

## E. Live server access — currently blocked, needs your hands

From this machine, over Tailscale:
- `tailscale ping the-eye-beta-server` → succeeds, 3ms, direct (no relay). Network layer is fine.
- `ssh the-eye-beta@100.77.87.18 "echo hi"` → publickey auth succeeds, then the shell
  hangs forever with zero output. Tested via hostname and raw IP, with and without
  verbose logging — same result every time.
- `curl http://100.77.87.18:7200/` and `:7020/v1/models` → also hang/timeout, no response.

Their own `.github/workflows/deploy.yml` notes the Tailscale ACL is scoped
`tag:ci → tag:server:22` for the CI runner; my personal node likely isn't covered by
whatever broader rule lets a normal operator reach 7200/7020, and the port-22 shell
hang is a separate, unexplained issue I can't diagnose without a working shell on the
box. Per their own `docs/headless-operations.md` "Everything Is Broken" runbook, step
0 is **stop live trading first**, before diagnosing — worth keeping in mind if this
turns out to be more than an ACL quirk.

**Needs you (or someone with confirmed working access) to run, directly on/to the box:**
```bash
tb status
docker compose ps
journalctl -u theeyebeta-admin -u theeyebeta-litellm -n 100
df -h        # rule out disk-full, which the runbook explicitly calls out
```

---

## F. TheEyeBetaDataAPI — production runbook not yet executed

`docs/PRODUCTION_RUNBOOK.md` in this repo is a generic template (placeholder domain
`api.yourdomain.com`, generic VPS instructions) — it reads like scaffolding that
hasn't been walked through for the real deployment yet, unlike TheEyeProd's
docs (which name real hosts/ports/services). Concretely outstanding per that runbook:

1. DB hardening — `deploy/db_security.sql` creating an `api_readonly` role, confirmed
   not yet run against production (no evidence either way from this checkout).
2. Real `.env` with production `API_KEY`/`JWT_SECRET`/`DATABASE_URL`/`CORS_ORIGINS`/`TRUSTED_HOSTS`.
3. Confirm `ADMIN_DATAAPI_CLIENT_ID`/`ADMIN_DATAAPI_CLIENT_SECRET` (referenced by
   TheEyeProd's `dataapi_control/client.py` bridge) are actually set on the
   TheEyeProd side and match a real client registered in this API — this is what lets
   the sectors/universe JSON endpoints in §C return real data instead of an error.
4. `/health` uptime monitoring + log centralization — not verified either way.

---

## G. 32-module production readiness (Prompt 6) — not attempted here

This needs a dedicated pass, not a bullet list bolted onto this doc — "production
ready for $10B AUM / SEC/FINRA scrutiny" spans access control review, audit-log
completeness, disaster recovery, and compliance sign-off, well beyond what's checkable
by reading code. The frontend-visibility side (making each module's admin page show
real data instead of a placeholder) was done in the `TheEyeBetaAdminFrontend` terminal
app this session — that's necessary but nowhere near sufficient for this prompt's
actual ask.
