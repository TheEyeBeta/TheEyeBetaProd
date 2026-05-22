# Rule 03 — Security

## Secrets

- **No secrets in source code, ever.** Not even in comments.
- All secrets are stored in sops-encrypted YAML files (`.sops.yaml` config at repo root).
- Decrypt at runtime via `sops exec-env secrets/dev.sops.yaml <command>`.
- Local dev overrides in `.env` (gitignored) are allowed ONLY for non-sensitive config.
- Use 1Password for team secret distribution. CLI: `op run -- make <target>`.

## Dependencies

- Pin all Python dependencies in `pyproject.toml` dep-groups.
- Run `gitleaks detect` (via pre-commit) on every commit.
- Dependabot PRs for security updates must be merged within 72 hours.

## Containers

- All images specify an explicit digest or semver tag — never `latest` in production.
- Compose dev images may use floating tags but must be pinned in k8s manifests.
- Non-root user in every Dockerfile (`USER nonroot`).

## Network

- Services communicate only via named Docker networks — never `network_mode: host` in prod.
- Postgres is never exposed on `0.0.0.0` in production infra.
- mTLS between all services in production (Tempo/Grafana Alloy handles dev).

## Code

- Validate all external input with Pydantic v2 models.
- Parameterize all SQL — never use f-strings to build queries.
- Never log PII, tokens, or passwords. Scrub structlog context at the boundary.
