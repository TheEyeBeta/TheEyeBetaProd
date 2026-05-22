# Rule 02 — Testing

## Philosophy

- Tests are written alongside code, not after.
- All new behaviour must have at least one test.
- Prefer narrow unit tests; use smoke/integration tests sparingly.

## Structure

```
tests/
├── unit/          # No I/O, no network, no DB — pure logic
├── integration/   # Single service, mocked dependencies
└── smoke/         # Full stack, requires `make up` to be running
```

## Conventions

- Test files: `test_<module>.py`. Test functions: `test_<behaviour>`.
- Use `pytest` fixtures. Avoid bare `setUp/tearDown`.
- Mark tests with `@pytest.mark.smoke` or `@pytest.mark.unit`.
- Smoke tests must be skippable: `pytest -m "not smoke"` must work in CI without infra.
- Use `pytest-cov` for coverage. Target ≥80% on library code.
- Fixtures that provision DB state must clean up after themselves (use transactions/rollback).

## Database Tests

- Use a separate `zinc_test` database (created by the smoke test fixture).
- Connection string from environment: `DATABASE_URL` (defaulting to `postgresql://zinc:zinc_dev@localhost:5432/zinc`).
- Never truncate prod schema in tests — use isolated schemas or transactions.

## CI Smoke Tests

- Smoke tests run in CI after `docker compose up -d --wait`.
- They connect to `localhost` ports exposed by compose.
- They must be idempotent and order-independent.
