# Rule 01 — Code Style

## Python

- Formatter: `ruff format` (line length 100). Run before committing.
- Linter: `ruff check --fix`. Fix all autofixable issues; explain others.
- Import order: stdlib → third-party → first-party (`zinc`). Enforced by ruff/isort.
- Type hints required on all public functions and methods. Use `from __future__ import annotations`.
- Docstrings: Google style. Required on all public classes and functions.
- Use `structlog.get_logger()` — never `print()`, never `logging.getLogger()` directly.
- Prefer `pathlib.Path` over `os.path`. Prefer f-strings over `.format()`.
- Async code: use `asyncio`. Prefer `anyio` for library code.

## C++

- Standard: C++20 minimum.
- Formatter: `clang-format` with `.clang-format` at repo root. Run on every file touched.
- Naming: `UpperCamelCase` for types, `snake_case` for functions/variables, `kConstantName` for constants, `MACRO_NAME` for macros.
- Use `std::span`, `std::string_view`, `std::optional` — avoid raw pointers in public APIs.
- Every `.cpp` file includes its own `.h` first (prevents missing-include bugs).
- No `using namespace std;` in headers.

## SQL

- All SQL files linted with `sqlfluff --dialect postgres`.
- Migration files named: `NNNN_description.py` (Alembic auto-numbering).
- Always write reversible migrations (include `downgrade()`).

## General

- No TODO/FIXME without a linked issue: `# TODO(#42): description`.
- No commented-out code in commits.
- All files end with a newline.
