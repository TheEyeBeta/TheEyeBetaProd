# ADR 0009: htmx + Jinja2 over React for the Admin Frontend

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/admin-service.md](../admin-service.md), [docs/architecture.md §9](../architecture.md#9-admin-service), [.cursor/rules/frontend-htmx.mdc](../../.cursor/rules/frontend-htmx.mdc)

---

## Context

theeyebeta needs an admin dashboard (Part 7.2) accessible over Tailscale for:

- Live system health and service status.
- Order blotter — review, approve, reject pending orders.
- Research proposal review — approve sends to master-orchestrator for execution.
- Backtest job submission and result review.
- Audit log browsing (read-only).

The dashboard has a small audience (1–3 operators), does not need to be a public product, and the team has no frontend engineers. The primary author is a Python/FastAPI developer.

---

## Decision

We will implement `admin-service` as a server-side rendered application using:

- **FastAPI** for HTTP routing and template rendering.
- **Jinja2** for server-side HTML generation.
- **htmx** (CDN) for interactive partial updates without a JavaScript framework.
- **Tailwind CSS** (CDN Play) for styling — no build step.
- **Chart.js** (CDN) for data visualisation, initialised via `data-chart` attributes.

**No build pipeline. No npm. No TypeScript. No React.**

---

## Consequences

### Positive
- **Zero frontend build tooling.** No webpack, vite, esbuild, or npm. One less thing to install, configure, maintain, secure, and update.
- **Python-developer-friendly.** The entire stack is Python + HTML + CSS. No context switch to TypeScript, JSX, or React paradigms.
- **Simplicity of deployment.** `admin-service` is a single Python container. No separate static-asset CDN, no SPA routing, no SSR hydration.
- **htmx partial updates.** `hx-get`/`hx-post` attributes replace 90% of what React state management handles for CRUD dashboards. Live feeds implemented with `hx-trigger="every 5s"`.
- **Security surface.** No `npm install` means no supply-chain risk from thousands of transitive JS dependencies. No client-side secrets exposure.
- **CSRF built-in.** FastAPI middleware handles CSRF tokens for all form submissions.

### Negative
- **Limited interactivity ceiling.** Complex multi-step wizard UIs or rich client-side state (drag-and-drop, real-time collaborative editing) are awkward with htmx. Not required now; would require revisiting this ADR if needed.
- **No hot module replacement.** Development iteration involves a full page reload (fast, but not HMR-fast).
- **htmx learning curve.** `hx-swap`, `hx-target`, `hx-trigger` semantics require a short adjustment period for developers unfamiliar with hypermedia-driven patterns.
- **Chart.js is not React-reactive.** Chart updates require re-rendering the `<canvas>` element via an htmx partial, not an in-place data mutation.

### Neutral
- The admin UI is internal-only and Tailscale-gated. UX polish is a lower priority than correctness and security.
- All mutating actions (order approval, service restart, SQL write) require a confirmation modal — enforced by `.cursor/rules/frontend-htmx.mdc`.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **React + Vite + TypeScript** | Requires frontend build toolchain; introduces npm supply-chain risk; requires TypeScript expertise; high maintenance overhead for a 1–3 user internal tool |
| **Next.js** | Same objections as React, plus SSR complexity |
| **Vue 3** | Same class of objections; lighter but still requires npm |
| **Streamlit / Gradio** | Designed for data science prototypes; limited layout control; non-standard event model; poor integration with existing FastAPI service |
| **Django admin** | Not a FastAPI project; would require Django as a second web framework |
| **Alpine.js** | Lighter than React but still JS-driven state; htmx hypermedia pattern is simpler for our CRUD-heavy use case |

---

## References

- [docs/admin-service.md](../admin-service.md)
- [docs/architecture.md §9](../architecture.md#9-admin-service)
- [.cursor/rules/frontend-htmx.mdc](../../.cursor/rules/frontend-htmx.mdc)
- [htmx documentation](https://htmx.org/docs/)
- [Hypermedia Systems (book)](https://hypermedia.systems/)
