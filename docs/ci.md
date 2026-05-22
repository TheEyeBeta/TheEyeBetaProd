# CI Matrix Documentation

## Overview

CI runs on GitHub Actions. Every push and PR triggers the pipeline.
The matrix ensures compatibility across supported Python versions.

## Matrix

| Dimension       | Values                        |
|-----------------|-------------------------------|
| `python-version`| `3.11`, `3.12`, `3.13`        |
| `os`            | `ubuntu-latest`               |

## Jobs

### `lint`
Runs on every push/PR. Does **not** spin up infra.

Steps:
1. Checkout
2. Set up Python (3.12 pinned — lint doesn't need the full matrix)
3. Install `uv`
4. `uv sync --group dev`
5. `ruff check .`
6. `ruff format --check .`
7. `gitleaks detect --no-git --source .`

### `test`
Runs the full matrix. Does **not** require infra.

Steps:
1. Checkout
2. Set up Python (matrix version)
3. Install `uv`
4. `uv sync --group dev`
5. `pytest -m "not smoke" --cov=libs --cov-report=xml`
6. Upload coverage to Codecov (optional)

### `smoke`
Runs only on `main` branch pushes and PRs with `smoke` label.

Steps:
1. Checkout
2. Set up Docker Buildx
3. `docker compose up -d --wait` (with 120s timeout)
4. Set up Python 3.12
5. Install `uv` + `uv sync --group dev`
6. `pytest -m smoke -v`
7. `docker compose down -v`

## Branch Strategy

- `main`: protected, requires CI green + 1 approval
- `feat/*`, `fix/*`, `chore/*`: feature branches, CI runs on PR
- Merge strategy: squash merge to `main`

## Secrets Required in GitHub

| Secret Name         | Purpose                         |
|---------------------|---------------------------------|
| `CODECOV_TOKEN`     | Coverage upload (optional)      |
| `DOCKER_USERNAME`   | Docker Hub push (optional)      |
| `DOCKER_PASSWORD`   | Docker Hub push (optional)      |

## Cache Strategy

- `uv` dependency cache keyed on `pyproject.toml` hash
- Docker layer cache via `actions/cache` with `type=gha`

## Failure Policy

- Any failed job blocks PR merge.
- `smoke` failure does not block non-`main` merges (it's advisory).
- Flaky tests must be fixed within one sprint or quarantined with `@pytest.mark.skip`.
