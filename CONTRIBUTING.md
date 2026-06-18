# Contributing to theeyebeta

---

## Table of Contents

1. [Branch Policy](#branch-policy)
2. [Conventional Commits](#conventional-commits)
3. [Pull Request Requirements](#pull-request-requirements)
4. [Code Review Expectations](#code-review-expectations)
5. [Adding a New ADR](#adding-a-new-adr)
6. [Adding a New Service](#adding-a-new-service)
7. [Adding a New Agent](#adding-a-new-agent)
8. [Adding a Migration](#adding-a-migration)
9. [Code Standards](#code-standards)
10. [Local CI Equivalent](#local-ci-equivalent)

---

## Branch Policy

We use **trunk-based development** with short-lived feature branches.

```
main                  protected — CI green + 1 approval required; no direct commits
│
├── feat/<kebab-name>    new behaviour (≤ 3 days; rebase onto main daily)
├── fix/<kebab-name>     bug fix
├── chore/<kebab-name>   non-functional: deps, tooling, docs, config
├── refactor/<name>      internal restructure, no behaviour change
└── ci/<name>            workflow / pipeline changes
```

**Rules:**

- Branches are created from and merged back to `main` only (no long-lived feature branches).
- Keep branches short — if a feature takes more than 3 days, decompose it into smaller PRs.
- Rebase onto `main` before opening a PR; do not use merge commits on feature branches.
- Squash-merge to `main` (GitHub enforces this via branch protection).
- Delete the branch after merge.

---

## Conventional Commits

Format: `<type>(<scope>): <subject>`

```
feat(oms): add partial-fill order handling
fix(risk-service): correct intraday VaR sign convention
chore(deps): bump pydantic 2.7 → 2.8
docs(adr): add 0009-broker-abstraction
refactor(guard-service): extract position-limit rule into own module
test(agent-runtime): add integration test for signal rejection
build(cpp): upgrade Eigen 3.4 → 3.5
ci(release): pin docker/build-push-action to v6.3.0
```

| Type | When to use |
|------|-------------|
| `feat` | New user-facing behaviour |
| `fix` | Bug fix |
| `chore` | Deps, tooling, non-code files |
| `docs` | Documentation only |
| `refactor` | Refactor without behaviour change |
| `test` | Adding or fixing tests |
| `build` | Build system, CMake, Conan, uv |
| `ci` | GitHub Actions workflows |
| `perf` | Performance improvement |

Scope is the service or component name: `oms`, `risk-service`, `guard-service`,
`cpp/order-book`, `db/migrations`, `infra`, `adr`, etc.

Subject: imperative mood, lowercase, ≤ 72 chars, no trailing period.

The `conventional-pre-commit` hook enforces this on every `git commit`.

---

## Pull Request Requirements

PRs are created with `gh pr create` or via the GitHub UI.
The [pull request template](.github/pull_request_template.md) is loaded automatically.

**Required in every PR:**

- [ ] Link to the issue this closes: `Closes #<n>` in the description.
- [ ] `make lint && make test` passes locally before pushing.
- [ ] New behaviour has tests (unit or integration as appropriate).
- [ ] If the PR changes the DB schema: migration reviewed, `downgrade()` implemented.
- [ ] If the PR affects the service map or architecture: `docs/architecture.md` updated.
- [ ] If the PR is an architectural decision: ADR added in `docs/adr/` (check `ls docs/adr/ | tail -1`
      for the next free number first — two ADRs have collided on the same number before).
- [ ] If the PR touches `services/`, `db/migrations/`, `docker-compose.yml`, `deploy/systemd/`,
      `config/`, or `.github/workflows/`: run the `doc-sync` skill
      (`.claude/skills/doc-sync/SKILL.md`) before requesting review.

**Required for UI changes (admin-service):**

- [ ] Screenshot or short screen recording showing before/after.
- [ ] Confirmation modal present for any mutating action.

**Required for C++ changes:**

- [ ] `_test.cpp` sibling exists or updated for the changed `.cpp`.
- [ ] `make build-cpp` passes on the PR runner.

---

## Code Review Expectations

**For authors:**

- Keep PRs small (≤ 400 lines changed; exceptions need a comment in the PR body).
- Respond to review comments within 1 working day.
- Don't resolve threads opened by the reviewer — let the reviewer resolve after verifying.
- If you disagree with a comment, explain why; don't silently ignore it.

**For reviewers:**

- Review within 1 working day of being assigned.
- Distinguish blocking (`must fix`) from advisory (`consider`) comments by prefixing.
- Approve only when you would be comfortable being on-call for this code.
- At least one approval required before merge; reviewer should not be the author.

---

## Adding a New ADR

An ADR is required for any decision that affects: service topology, database schema
strategy, messaging patterns, secret management, observability approach, CI/CD strategy,
or the C++ build system.

**Number scheme:** four zero-padded digits (`0001`, `0042`, …).  
**Title scheme:** five-word kebab-case slug.

```bash
# 1. Pick the next number
ls docs/adr/ | tail -1       # e.g. 0007-container-strategy.md → next is 0008

# 2. Create the file from the template
cp docs/templates/adr.md docs/adr/0008-five-word-kebab-title.md

# 3. Fill in all sections (Context, Decision, Consequences, Alternatives)

# 4. Commit
git add docs/adr/0008-five-word-kebab-title.md
git commit -m "docs(adr): add 0008 five word kebab title"
```

**Template fields** (all required):

| Field | Guidance |
|-------|---------|
| **Status** | `Proposed` → `Accepted` → optionally `Deprecated` or `Superseded by [NNNN]` |
| **Context** | The forces at play. Be specific — what problem is this solving right now? |
| **Decision** | One clear sentence: "We will use X for Y." |
| **Consequences +** | Concrete benefits you expect. |
| **Consequences −** | Trade-offs you are accepting. |
| **Alternatives** | Table of options considered and why each was rejected. |

---

## Adding a New Service

Use the scaffold script which creates the directory structure, `pyproject.toml`,
`Dockerfile`, and a stub FastAPI app in one command:

```bash
bash scripts/new_service.sh <service-name>
# e.g.
bash scripts/new_service.sh portfolio-service
```

The script:
1. Creates `services/portfolio-service/` with the standard layout.
2. Adds the service to the uv workspace (picked up automatically on next `uv sync`).
3. Adds a placeholder entry to `docker-compose.yml`.
4. Prints the checklist of manual steps remaining.

**Manual steps after the script** (also printed by the script):

- [ ] Pick a port from the [port map](docs/architecture.md#22-port-map) and add it there.
- [ ] Add the service name to the `build-images` matrix in `.github/workflows/release.yml`.
- [ ] Write the service README from [docs/templates/README.md](docs/templates/README.md).
- [ ] Add routes to `docs/architecture.md §3.1`.
- [ ] Write the first migration if the service owns any tables.

---

## Adding a New Agent

Use the agent scaffold script:

```bash
bash scripts/new_agent.sh <agent-name>
# e.g.
bash scripts/new_agent.sh sentiment-agent
```

The script creates the agent module under `services/agent-runtime/src/agents/`
with the standard `BaseAgent` interface, a prompt template, and a test stub.

See [docs/agents.md](docs/agents.md) for the agent architecture and the
`BaseAgent` contract.

---

## Adding a Migration

```bash
# Generate the revision
make db-revision MSG="add portfolio_positions table"

# Review the generated file
# • implement downgrade()
# • check FK constraints use ON DELETE RESTRICT
# • check timestamps are TIMESTAMPTZ NOT NULL

git add db/migrations/versions/
git commit -m "build(db): add portfolio_positions migration"
```

Rules enforced by `.claude/rules/sql.md` and reviewed in CI:
- All FKs `ON DELETE RESTRICT` unless an ADR justifies otherwise.
- All timestamps `TIMESTAMPTZ NOT NULL`.
- `create_hypertable()` in the same revision as `CREATE TABLE` for time-series tables.
- `audit_log` is append-only — never add `UPDATE`/`DELETE` grants.

---

## Code Standards

All enforced by pre-commit hooks and CI — no manual checks needed.

| Language | Formatter | Linter | Type check |
|----------|-----------|--------|-----------|
| Python | `ruff format` + `black` | `ruff check` | `mypy --strict` (libs/) |
| C++ | `clang-format` (LLVM/100-col) | `clang-tidy` | — |
| SQL | — | `sqlfluff` (postgres) | — |

Full rules: `.claude/rules/` (Claude Code), `.cursor/rules/` (Cursor IDE).

---

## Local CI Equivalent

Run this before pushing to catch everything CI will catch:

```bash
make lint          # ruff + black --check + mypy + clang-format --dry-run + sqlfluff
make test          # pytest -m "not integration and not smoke"
make test-int      # pytest -m integration (testcontainers — Docker required)
make build-cpp     # cmake + conan (if cpp/ has CMakePresets.json)
```
