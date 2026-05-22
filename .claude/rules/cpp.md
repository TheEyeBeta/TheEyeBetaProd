---
paths: ["cpp/**"]
---

# C++ Rules

## Standard & Compiler

- **C++20 only.** No C++17 fallbacks; use concepts, ranges, `std::span`, designated initialisers freely.
- Compile with `-Wall -Wextra -Wpedantic -Werror` in CI.
- No RTTI (`-fno-rtti`) unless a specific subsystem explicitly opts in with a comment explaining why.

## Error Handling

- **No exceptions in hot paths.** Use `std::expected<T, E>` for fallible operations on any
  code path that is called in a loop or from a nanobind boundary.
- Exceptions are permitted in one-time startup/shutdown code only.
- Error types must be `enum class` values or small value types — never heap-allocated polymorphic errors.

## Dependencies

- **Eigen** for all matrix/vector algebra — do not roll bespoke BLAS wrappers.
- **nlohmann::json** for JSON serialisation/deserialisation.
- All other deps managed via **Conan 2** (`conanfile.py` at `cpp/`).
- Never `#include` a header that is not declared in the same target's `CMakeLists.txt`.

## Documentation

- Every **public header** must open with a Doxygen block:
  ```cpp
  /**
   * @file   foo.h
   * @brief  One-line description.
   *
   * Longer description if needed.
   */
  ```
- Every public function/method must have `@brief`, `@param`, and `@return` tags.
- Internal (`.cpp`-only) functions: inline comment is sufficient.

## Testing

- Every `foo.cpp` must have a sibling `foo_test.cpp` in the same directory.
- Tests use **GoogleTest** (`gtest_main`).
- Test naming: `TEST(FooSuite, GivenX_WhenY_ThenZ)`.
- Mocks only for external system boundaries (network, filesystem, nanobind Python calls).

## Formatting & Linting

- **clang-format** with `BasedOnStyle: LLVM`, `ColumnLimit: 100`.
  Config lives at `cpp/.clang-format` (overrides repo-root `.clang-format` for C++ paths).
- **clang-tidy** with the following check families enabled:
  - `modernize-*`
  - `performance-*`
  - `bugprone-*`
  - `cppcoreguidelines-pro-type-*`
- `make lint-cpp` must pass before any PR merges.
- No `reinterpret_cast` without an accompanying `// NOLINT` comment explaining the necessity.

## Python Bindings

- Bindings use **nanobind** (not pybind11).
- Binding files named `<module>_nb.cpp`; never mix binding code with implementation.
- The nanobind module must be tested from Python in `tests/smoke/test_cpp_<module>.py`.
