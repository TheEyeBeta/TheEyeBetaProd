# ADR 0006: Monorepo with Plain GNU Make as the Task Runner

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §14](../architecture.md#14-repository-layout), [Makefile](../../Makefile)

---

## Context

theeyebeta spans Python services, C++ compute modules, SQL migrations, Docker Compose infra, and GitHub Actions CI. We need a task runner that:

1. Works identically in local dev, CI (ubuntu-latest), and the production Mac mini.
2. Requires zero extra tooling to install beyond what a C++ developer already has.
3. Supports the `make <tab>` discoverability workflow.
4. Handles heterogeneous targets: Python linting, CMake builds, Docker Compose, secret decryption.

We also need a repository layout that keeps all of the above in one place without coupling service deployments.

---

## Decision

We will use a **monorepo** (single git repository) with **GNU Make** as the sole task runner.

- A single `Makefile` at repo root with `##` auto-doc comments generates `make help` output.
- uv workspaces handle Python dependency resolution across all members (`services/*`, `libs/*`, `tb/`).
- Each service has its own `pyproject.toml` and `Dockerfile` but shares root-level tooling config.
- No Bazel, Pants, nx, Turborepo, or similar build orchestration system.

---

## Consequences

### Positive
- `make help` is the single entry point for all operations — no README-diving required.
- GNU Make is pre-installed on every Linux/macOS machine. Zero additional install for new contributors.
- Pattern rules (`logs-%:`) give service-specific targets (`make logs-postgres`) without listing each service manually.
- Makefile targets are trivially aliasable in CI (`make lint` === the CI lint job).
- uv workspace resolves all Python deps in one lockfile — no per-service lockfile drift.
- Cross-service changes (e.g. bumping pydantic) are atomic: one commit, one lockfile update, one PR.

### Negative
- GNU Make's tab-indentation rule trips up editors and contributors unfamiliar with Makefiles.
- Make's dependency tracking is file-based; it does not understand Python or Docker cache invalidation. Targets are largely `.PHONY` — no incremental build benefit.
- As the monorepo grows, CI must become smarter about which jobs to run on which paths (path-filtered triggers). Plain Make cannot do this; GitHub Actions path filters must be added per workflow.
- Make does not parallelize well across heterogeneous targets without manual `-j` tuning.

### Neutral
- C++ builds use CMake presets called from Make (`make build-cpp` delegates to `cmake --preset`). Make is the orchestrator; CMake is the actual C++ build system.
- The monorepo does not imply a monolith. Each service is independently deployable via its own Dockerfile and image tag.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Bazel** | Powerful but steep learning curve; Starlark DSL; overkill for a small team on one host |
| **Pants** | Python-centric; C++ support is experimental; another DSL to learn |
| **nx / Turborepo** | Node-ecosystem tooling for a Python-primary project; adds npm as a dependency |
| **Just** (justfile) | Cleaner syntax than Make but not pre-installed; adds an install step; less CI tool support |
| **Polyrepo** | Eliminates the monorepo problem but creates cross-service change coordination overhead; tooling duplication |
| **Task (go-task)** | Similar to Just; requires Go binary install; no benefit over Make for our use case |

---

## References

- [GNU Make documentation](https://www.gnu.org/software/make/manual/)
- [uv workspaces](https://docs.astral.sh/uv/concepts/workspaces/)
- [Makefile](../../Makefile)
- [pyproject.toml — workspace root](../../pyproject.toml)
