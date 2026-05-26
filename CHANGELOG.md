# Changelog

All notable changes to **theeyebeta** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Conventional Commits](https://www.conventionalcommits.org/)
for git history. Each phase below corresponds to a `P-*` task identifier from
the build plan.

## [Unreleased]

### Added — `admin-service` (Phase: operator dashboard)

**API + service skeleton**
- **P-AD-01** — FastAPI app on port 7200 (binds `0.0.0.0` for Tailscale), JWT
  RS256 auth with bcrypt password gate, refresh-token rotation in Redis,
  CORS for Cloudflare + Tailscale origins, slowapi rate limiting
  (100/minute default, 20/minute on write endpoints).
- **P-AD-R-orders** — `GET /admin/orders/pending`, `GET /admin/orders/{id}`,
  `POST /admin/orders/{id}/approve`, `POST /admin/orders/{id}/reject`
  with idempotency keys + audit logging.
- **P-AD-R-audit** — `GET /admin/audit/log` (paginated, filters), proxied
  `GET /admin/audit/verify`, `GET /admin/audit/checkpoints`.
- **P-AD-R-agents** — `GET /admin/agents`, `GET /admin/agents/{id}/runs`,
  `POST /admin/agents/{id}/run` (proxies to `agent-runtime`),
  `GET /admin/agents/{id}/constitution`.
- **P-AD-R-guard** — `GET /admin/guard/violations` (agent / severity /
  unresolved filters), `POST /admin/guard/violations/{id}/resolve`.
- **P-AD-R-services** — `GET /admin/services/status`,
  `POST /admin/services/{name}/restart` (whitelisted services only).
- **P-AD-R-backtest** — `POST /admin/backtest` (publishes
  `backtests.requested` on NATS), `GET /admin/backtest/{id}/results`,
  `GET /admin/backtest` (list recent).
- **P-AD-R-costs** — `GET /admin/costs/daily` (last N days),
  `GET /admin/costs/by-agent` (per `YYYY-MM`).
- **P-AD-R-sql** — read-only `POST /admin/sql/query` (`SELECT`-only, parsed
  via `sqlparse`), write-with-confirmation `POST /admin/sql/execute`
  (`X-Confirm: true` header + `X-Idempotency-Key` required).
- **P-AD-R-proposals** — `GET /admin/proposals`, detail/approve/reject
  endpoints; approve optionally publishes a validation backtest request.
- **P-AD-LOAD** — in-process locust harness (`tests/test_load.py`) +
  k6 script + Cloudflare/Tailscale access checklist in
  `docs/admin-service.md`. SLO: p99 < 500 ms on `GET /admin/orders/pending`.

**Server-rendered admin UI (Tailwind + htmx + Chart.js)**
- **P-FE-00** — `templates/base.html` layout, `_nav.html`, `_modal.html`,
  dark-mode toggle, JWT cookie + HX-Redirect handling, severity-colour
  styles for violations (`.severity-low/.medium/.high/.critical`).
- **P-FE-dashboard** — `/admin/` page: 4 stat cards (pending orders, active
  agents, today's cost, last audit verify), Run Daily Backtest +
  Verify Audit Chain quick actions, embedded Grafana iframe.
- **P-FE-orders** — `/admin/orders` page: pending-orders table with
  expandable agent rationale, approve (direct row swap) + reject (modal
  with reason).
- **P-FE-audit** — `/admin/audit` page: filter form (entity, actor, since,
  limit), paginated table, "Verify Chain" with inline colour-coded result.
- **P-FE-agents** — `/admin/agents` two-pane page: agent list (with 7-day
  success rate badge) + right pane that swaps between recent runs and the
  constitution view (`highlight.js`-rendered Markdown + JSON schema).
- **P-FE-violations** — `/admin/violations` page: filter form, severity-
  coloured rows, click-to-expand JSON detail, per-row resolve modal.
- **P-FE-costs** — `/admin/costs` page: daily stacked bar chart + per-agent
  doughnut + month-to-date tables by vendor and agent. Chart.js instances
  rebuild after htmx swaps; `__USD__` sentinel re-bound to a JS formatter.
- **P-FE-sql** — `/admin/sql` page: CodeMirror 5 SQL editor, read/write
  mode toggle, write-confirmation modal requiring the phrase
  `I UNDERSTAND` + server-minted UUIDv7 idempotency key.
- **P-FE-proposals** — `/admin/proposals` page: pending/approved/rejected
  tabs, category filter, markdown-it-rendered rationale, evidence links
  that deep-link to backtest results, approve modal triggers a validation
  backtest with progress polling, `sessionStorage`-backed "defer" state.
- **P-FE-FINAL** — Playwright + axe-core e2e suite
  (`services/admin_service/tests/test_frontend.py`, marker
  `@pytest.mark.frontend`). Spins a real uvicorn server in a background
  thread, mints an RS256 keypair + bcrypt hash for the real login flow,
  drives every page through one htmx swap, asserts no console / page
  errors, and runs an axe-core WCAG 2.0/2.1 A+AA audit asserting **zero
  critical violations**.

### Documentation
- `docs/admin-service.md` — per-page sections for the eight UI pages,
  the load-test SLO, the Cloudflare/Tailscale access checklist, and the
  P-FE-FINAL frontend acceptance bar.

### Dev tooling
- `pyproject.toml` — added `playwright>=1.48` and `pytest-playwright>=0.5`
  to the workspace `[dependency-groups] dev`; registered the `frontend`
  pytest marker; mapped `zinc-test` as a workspace source so `uv sync`
  resolves it from `libs/zinc_test`.

### Fixed — Build audit follow-up (2026-05-26)
Driven by `docs/build-audit-20260525-1749.md`:

- **17.19 — agent constitution drift (6 of 30 missing or unloadable)** — three
  files that lived at the `agents/` root with the wrong `.md` extension were
  moved to their canonical department directory and renamed to `.agent.md`
  so `load_constitution()` (`rglob("*.agent.md")`) can pick them up:
  `agents/macro-lead.md` → `agents/markets/macro-lead.agent.md`,
  `agents/news-sentiment.md` → `agents/markets/news-sentiment.agent.md`,
  `agents/technical-analyst.md` → `agents/research/technical-analyst.agent.md`.
  Three previously-missing constitutions were authored:
  `agents/markets/geopolitical-risk.agent.md`,
  `agents/markets/liquidity.agent.md`,
  `agents/client/client-lead.agent.md`.
  The orphan `agents/master-orchestrator.md` duplicate was deleted (canonical
  copy lives at `agents/top/master-orchestrator.agent.md`). The runtime now
  loads **30 / 30** constitutions.
- **17.11 — `services/oms/tests/test_oms_e2e.py` was missing per spec naming
  convention** — added a stub e2e file under that exact path that delegates
  to `test_approve.py` + `test_reconciliation.py` (the substantive lifecycle
  test continues to live at `tests/test_oms_e2e.py`).
- **17.25 — `docs/build-log.md` ended at section 17.11** — extended with full
  P-* checklists for sections 17.12 – 17.25 (broker adapter, backtest engine,
  audit service, R&D agent, admin backend, admin frontend, agent
  constitutions, networking, CI/CD, observability, security hardening,
  testing infrastructure, documentation). Added Lessons Learned §4 capturing
  the agent extension drift root cause + suggested test-side prevention.

### Pending verification (post-merge, manual on production host)
- **P-AD-LOAD acceptance** — execute the locust/k6 load profile on the
  Mac mini and confirm p99 < 500 ms with error rate ≤ 1 %.
- **P-AD-LOAD access checklist** — tick every Cloudflare + Tailscale row
  in `docs/admin-service.md §"End-to-end access checklist"`.
- **P-FE-FINAL execution** — on a dev box with browsers installed:
  `uv sync --group dev && playwright install chromium && pytest -m frontend`.
  Acceptance: all e2e tests pass, axe-core reports 0 critical violations.
- **Audit re-run** — re-execute `docs/build-audit-*.md` once Docker, Tailscale,
  and live DB are reachable to clear the SKIP_DOCKER / SKIP_DB / SKIP_LINUX
  rows (~24 checks across sections 17.0, 17.1, 17.3, 17.4, 17.6, 17.10, 17.20,
  17.21, 17.23, plus CSI-3..5).

[Unreleased]: https://github.com/theeyebeta/theeyebeta/compare/ff1b2dc...HEAD
