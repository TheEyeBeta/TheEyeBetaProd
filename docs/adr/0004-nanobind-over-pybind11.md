# ADR 0004: nanobind over pybind11 for C++/Python Bindings

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §8](../architecture.md#8-c-compute-layer), [.cursor/rules/cpp.mdc](../../.cursor/rules/cpp.mdc)

---

## Context

theeyebeta implements performance-critical paths in C++20 (order book, vectorised backtester, risk calculations) and exposes them to Python services via bindings. We need a binding library that:

1. Compiles fast (short inner-loop dev cycle).
2. Produces small, low-overhead Python extension modules.
3. Supports C++20 features (concepts, `std::span`, `std::expected`).
4. Has a clean API for exposing value types, enums, and async-friendly buffer protocols.
5. Is actively maintained and has a clear long-term trajectory.

---

## Decision

We will use **nanobind** for all C++/Python bindings.

Binding files are named `<module>_nb.cpp` and compiled into extension modules importable from Python as `from order_book import OrderBook`.

---

## Consequences

### Positive
- nanobind is designed as the successor to pybind11 by the same author (Wenzel Jakob). It is more opinionated, which means less boilerplate per binding.
- **Compilation speed:** nanobind modules compile 2–4× faster than equivalent pybind11 modules due to reduced template instantiation depth.
- **Binary size:** nanobind produces ~50% smaller `.so` files — meaningful when shipping via wheel.
- **C++17/20 features:** nanobind natively supports `std::span`, `std::optional`, `std::variant`, and Eigen matrix types via `nanobind/stl/` headers, with no adapter boilerplate.
- Zero-copy buffer protocol: numpy arrays and `std::span` exchange data without copies.
- `nb::ndarray<>` gives direct access to numpy / PyTorch tensors for the backtester's vectorised operations.

### Negative
- nanobind is younger than pybind11 (released 2022 vs 2015). Third-party guides and Stack Overflow answers are sparse.
- pybind11 has a larger ecosystem of pre-written type casters for niche types. We may need to write custom casters for domain types.
- Migration path from pybind11 to nanobind is non-trivial if we ever import a third-party library that exposes its own pybind11 bindings.

### Neutral
- The `PYBIND11_*` macros are replaced by `NB_MODULE` and `nb::class_<>`. Syntax is similar enough that developers familiar with pybind11 adapt within an hour.
- nanobind requires Python ≥ 3.8 and a C++17 compiler minimum; we use C++20 throughout.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **pybind11** | More mature but slower compilation, larger binaries, no first-class C++20 std::span support, considered legacy by its own author |
| **ctypes / cffi** | No class binding; no automatic type conversion; massive boilerplate for struct-heavy APIs |
| **Cython** | Requires `.pyx` files with Cython-specific syntax; adds a compilation pipeline step; less ergonomic for C++ class hierarchies |
| **SWIG** | Generates large, unreadable glue code; poor C++20 support; no active development focus on modern C++ |
| **maturin / PyO3 (Rust)** | We are building the hot path in C++; rewriting in Rust is out of scope |

---

## References

- [nanobind documentation](https://nanobind.readthedocs.io/)
- [nanobind vs pybind11 benchmark](https://nanobind.readthedocs.io/en/latest/benchmark.html)
- [docs/architecture.md §8](../architecture.md#8-c-compute-layer)
- [cpp/.clang-format](../../cpp/.clang-format)
