# CLAUDE.md — theeyebeta

> **Read this file in full before taking any action.**
> It is the authoritative project-memory for Claude Code and every AI agent in this repo.
> Path-scoped rules live in `.claude/rules/*.md`; dev-subagent specs in `.claude/agents/*.md`.

---

## 1. Project Identity

**Name:** theeyebeta
**Description:** A self-hosted, real-time market-intelligence and algorithmic-research platform
running on a dedicated Mac mini (Linux), combining a Python/FastAPI backend, C++ compute
modules, and a full observability stack.

---

## 2. Production Host

| Item | Value |
|------|-------|
| Host | Mac mini — Linux (bare-metal, on-prem) |
| Port map | See `docs/architecture.md §2.2` |
| Process supervisor | `tb` CLI (custom — see §6 below) |
| Secrets | sops + age; 1Password for team distribution |

> Do **not** infer port numbers from code. Always consult `docs/architecture.md §2.2`.

---

## 3. Repository Layout

Canonical tree is defined in `docs/architecture.md §14.1`.
Until that file exists, consult `docs/repo-layout.md` for the bootstrap scaffold.

Rules of thumb:
- `services/<name>/` — one directory per deployable service.
- `libs/` — shared Python packages (imported by services, never deployed alone).
- `cpp/` — C++20 source; built with CMake + Conan; Python bindings via nanobind.
- `infra/` — Docker Compose configs, k8s manifests (future), observability provisioning.
- `docs/adr/` — Architecture Decision Records (ADR template: `docs/templates/adr.md`).
- `tests/` — `unit/` (no I/O), `integration/`, `smoke/` (requires live infra).

---

## 4. Conventions

### Python
- **Version:** 3.12
- **Framework:** FastAPI (async throughout — no sync route handlers)
- **Linter / formatter:** `ruff check --fix` then `ruff format` (line-length 100)
- **Type checker:** `mypy --strict` — all public symbols annotated
- **Style:** Black-compatible (ruff handles it); Google-style docstrings
- **Logging:** `structlog` only — no `print()`, no bare `logging.getLogger()`
- **Validation:** Pydantic v2 models for all external input and inter-service contracts
- **Migrations:** Alembic — reversible scripts in `services/<svc>/migrations/`

### C++
- **Standard:** C++20
- **Build:** CMake ≥ 3.28; dependencies via Conan 2
- **Python bindings:** nanobind (not pybind11)
- **Formatter:** `clang-format` (`.clang-format` at repo root)
- **Naming:** `UpperCamelCase` types, `snake_case` functions/variables, `kPascalCase` constants

### SQL
- All SQL linted with `sqlfluff --dialect postgres`
- Migrations: `alembic upgrade head` per service (wrapped by `make db-migrate`)
- **Never** DELETE from `audit_log` — rows are immutable by policy

### Commits
- Format: `<type>(<scope>): <subject>` — [Conventional Commits](https://www.conventionalcommits.org/)
- Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`
- No secrets, no commented-out code, no `TODO` without a linked issue

---

## 5. Where Rules Live

| Path | Purpose |
|------|---------|
| `.claude/rules/01-code-style.md` | Python, C++, SQL style details |
| `.claude/rules/02-testing.md` | Test pyramid, fixtures, coverage targets |
| `.claude/rules/03-security.md` | Secrets, input validation, PII policy |
| `.claude/rules/04-infrastructure.md` | Docker, service standards, OTEL wiring |
| `.claude/agents/dev.md` | General dev subagent (lint, test, build) |
| `.claude/agents/infra.md` | Infra subagent (compose, migrations) |

---

## 6. Commands the AI May Run Autonomously

The following commands are **pre-approved** — no confirmation needed:

```
make lint            # ruff + clang-format check + sqlfluff + gitleaks
make test            # pytest -m "not smoke"
make build-cpp       # CMake configure + build
tb status            # show service health on the production host
tb logs <svc>        # tail logs for a named service
```

Every other command that **mutates production** requires explicit user confirmation
before execution. This includes but is not limited to:

| Command class | Confirmation required |
|---------------|-----------------------|
| `make deploy` / `tb deploy <svc>` | Yes — state the version and service |
| `make db-migrate` against prod | Yes — show migration plan first |
| `tb restart <svc>` (prod) | Yes — state reason |
| Any `docker compose` on the live host | Yes |
| `sops` decrypt of prod secrets | Yes |

---

## 7. Hard Limits — Never Do These

1. **`git push --force`** on any branch — use `--force-with-lease` if absolutely required,
   and only after explicit user instruction.
2. **Delete rows from `audit_log`** — this table is append-only by policy; violations break
   compliance requirements.
3. **Toggle live-trading mode** — the `LIVE_TRADING=true` flag may only be set by the user
   directly; an agent must never write or export this environment variable.
4. **Commit plaintext secrets** — all secrets through sops + age, no exceptions.
5. **Skip pre-commit hooks** (`--no-verify`) — fix the failure instead.

---

## 8. CI

- Platform: GitHub Actions (`.github/workflows/ci.yml`)
- Matrix: Python 3.12 on `ubuntu-latest`; smoke tests only on `main` push or `smoke`-label PRs
- CI must be green before any PR merges into `main`
- See `docs/ci.md` for the full job description

---

## 9. Quick Reference

```bash
make up           # start all local infra (postgres, redis, nats, minio, otel stack)
make down         # stop infra
make lint         # all linters
make format       # auto-format (ruff + clang-format)
make test         # unit + integration tests
make test-smoke   # full-stack smoke tests (requires make up)
make db-migrate   # alembic upgrade head — LOCAL only
make build-cpp    # CMake + Conan build
```

> **When in doubt, ask.** Do not guess at production config, port numbers, or
> deployment targets — always read `docs/architecture.md` first.
