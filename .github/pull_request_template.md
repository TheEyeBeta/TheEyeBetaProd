## Summary

<!-- One paragraph describing what this PR does and why. -->

Closes #<!-- issue number -->

---

## Type of change

- [ ] `feat` — new behaviour
- [ ] `fix` — bug fix
- [ ] `refactor` — internal restructure, no behaviour change
- [ ] `chore` — deps / tooling / docs / config
- [ ] `ci` — workflow changes
- [ ] `build` — CMake / Conan / uv

---

## Checklist

**All PRs**

- [ ] `make lint && make test` passes locally
- [ ] New behaviour has tests (unit or integration)
- [ ] No secrets, credentials, or PII in the diff
- [ ] Commit messages follow Conventional Commits

**If DB schema changed**

- [ ] Migration generated with `make db-revision MSG="..."`
- [ ] `downgrade()` implemented
- [ ] FKs use `ON DELETE RESTRICT` (or ADR justification)
- [ ] Timestamps are `TIMESTAMPTZ NOT NULL`

**If architecture changed**

- [ ] `docs/architecture.md` updated (service map, port map, or data model)
- [ ] ADR added in `docs/adr/` — see [CONTRIBUTING.md §Adding a New ADR](../CONTRIBUTING.md#adding-a-new-adr)

**If admin-service UI changed**

- [ ] Screenshot or screen recording attached below
- [ ] Confirmation modal present for mutating actions

**If C++ changed**

- [ ] `_test.cpp` sibling exists or updated
- [ ] `make build-cpp` passes

---

## Screenshots / recordings

<!-- Required for admin-service UI changes. Drag & drop images here. -->

---

## Testing notes

<!-- How did you test this? What edge cases did you consider? -->
