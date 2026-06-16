# Lint Manual Review — noqa items

Generated: 2026-06-13. All items below were suppressed with `# noqa` because they are
false positives or deliberate design decisions. Each entry states the rule, location, and rationale.

---

## ANN401 — Dynamically typed `Any`

| File | Line | Rationale |
|------|------|-----------|
| `db/verify_full.py` | 109 | `**kwargs` to psycopg3 `connect()` are heterogeneous by design |
| `db/verify_full.py` | 837 | Internal helper returns row-tuple-or-None; narrowing adds no value |
| `libs/zinc_native/zinc_native/__init__.py` | 11 | PEP 562 `__getattr__` must return `Any` |
| `services/agent_runtime/src/agent_runtime/math_tool.py` | 57, 64, 75 | Functions accept raw JSON-decoded input before type-checking; Any is the correct annotation |
| `services/broker_adapter_alpaca/src/broker_adapter_alpaca/adapter.py` | 58 | Alpaca SDK `TradingStream` type is not publicly exported |

---

## S608 — Possible SQL injection via f-string

| File | Lines | Rationale |
|------|-------|-----------|
| `db/verify_full.py` | 962, 1030, 1050 | Table/column names sourced from internal `EXPECTED_TABLES` / `cleanup_ids` constants, not user input |
| `services/data_ingestion/src/data_ingestion/writers/postgres_writer.py` | 172, 245, 284, 370, 463 | `{conflict}` variable is a hardcoded `ON CONFLICT … DO UPDATE/NOTHING` clause constructed from `self._upsert` bool — not user-controlled. Suppressed via per-file-ignore in `pyproject.toml`. |

---

## SIM108 — Prefer ternary over if/else

| File | Line | Rationale |
|------|------|-----------|
| `db/verify_full.py` | 73 | Multiline if/else is more readable than a 60-char ternary |
| `libs/zinc_schemas/src/zinc_schemas/constitution.py` | 110 | Ternary with different list expressions on each branch exceeds line length and hurts readability |
| `scripts/list_pending_migrations.py` | 95 | `str()` cast in the ternary branch makes a long, harder-to-read expression |
| `scripts/probe_massive_intraday.py` | 53 | Two-branch ternary with different function calls (`json.dumps` vs `str`) is clearer as if/else |

---

## SIM117 — Nested `with` statements

| File | Line | Rationale |
|------|------|-----------|
| `services/data_ingestion/src/data_ingestion/observability.py` | 119 | `observe_duration` and `span` are distinct async context managers with different semantics; combining would obscure their roles |
| `services/data_ingestion/src/data_ingestion/pipeline.py` | 95 | Same pattern — two distinct async context managers |
| `services/data_ingestion/src/data_ingestion/writers/postgres_writer.py` | 95 | Same pattern |

---

## SIM102 — Nested `if` statements

| File | Line | Rationale |
|------|------|-----------|
| `services/guard_service/src/guard_service/validator.py` | 479 | Outer `if` guards universe membership; inner `if` guards allowed_markets. Merging with `and` hides the two-level logic |

---

## N818 — Exception name not ending in `Error`

| File | Line | Rationale |
|------|------|-----------|
| `services/agent_runtime/src/agent_runtime/guard.py` | 22 | `GuardViolation` is an established API name used across multiple callers; renaming would break the public interface |

---

## S105 — Possible hardcoded password

| File | Line | Rationale |
|------|------|-----------|
| `db/verify.py` | 14 | `PASS = "✓"` — unicode check-mark symbol, not a credential |
| `services/agent_runtime/src/agent_runtime/guard_client.py` | 21 | `_OUTCOME_PASS = "PASS"` — protocol outcome string, not a credential |

---

## S110 — `try/except/pass`

| File | Line | Rationale |
|------|------|-----------|
| `db/verify_full.py` | 965 | Non-privilege errors (e.g. empty table) are benign during this verification probe |

---

## S603 — `subprocess` with untrusted input

| File | Line | Rationale |
|------|------|-----------|
| `libs/zinc_test/src/zinc_test/_infra.py` | 95 | Trusted internal seeds script path; not user-supplied |

---

## UP047 — Generic function should use type parameters

| File | Line | Rationale |
|------|------|-----------|
| `services/data_ingestion/src/data_ingestion/observability.py` | 113 | `TypeVar T` is declared at module level and referenced in a `Callable` generic; rewriting to PEP 695 type-param syntax is not compatible with the `Callable[[], Awaitable[T]]` annotation form |

---

## E501 — Line too long

| File | Lines | Rationale |
|------|-------|-----------|
| `db/verify.py` | 133, 143, 153 | Assertion strings with long failure detail; splitting would harm readability |
| `db/verify_full.py` | 1160 | Diagnostic f-string; shortening would hide useful failure context |
| `services/data_ingestion/src/data_ingestion/writers/parquet_writer.py` | 59, 64 | Path format string and method signature; cannot split without indirection |
| `services/guard_service/src/guard_service/validator.py` | 496 | Long `set()` constructor with fallback; splitting the expression adds noise |
| `workers/supabase_sync_worker.py` | 55 | Nested dict literal for metadata; indentation makes splitting impractical |

---

## F811 — Redefinition of unused name from import

| File | Lines | Rationale |
|------|-------|-----------|
| `libs/zinc_test/src/zinc_test/fixtures/database.py` | 49, 50, 51 | pytest fixture parameters intentionally shadow re-exported fixture imports for fixture-resolution purposes |
