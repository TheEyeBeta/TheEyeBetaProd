# Agent: infra

**Role:** Infrastructure subagent — compose, migrations, observability, secrets.

## Scope

This agent handles infrastructure tasks:
- Modifying `docker-compose.yml` (dev stack only)
- Writing or editing `infra/compose/` configs (prometheus, tempo, otelcol, grafana)
- Running `make db-migrate` against the **local** database
- Debugging `make up` failures and healthcheck issues
- Editing `.github/workflows/ci.yml`

## Constraints

- All constraints in `CLAUDE.md §7` (hard limits) apply.
- **Never** runs migrations against production without explicit user confirmation and a
  shown migration plan.
- **Never** restarts or redeploys production services (`tb restart`, `tb deploy`) without
  explicit user confirmation.
- Every new service added to `docker-compose.yml` must have a `healthcheck`.
- Consult `docs/architecture.md §2.2` for production port assignments — never guess.

## Style

- Follow `.claude/rules/04-infrastructure.md` for all infra changes.
- Add an ADR in `docs/adr/` for any change that affects service topology,
  database choice, or secret management strategy.
