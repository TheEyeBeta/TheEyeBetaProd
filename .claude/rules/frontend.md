---
paths: ["services/admin_service/templates/**", "services/admin_service/static/**"]
---

# Frontend Rules (Admin Service)

## Stack — No Build Step

- **Jinja2** templates rendered server-side by FastAPI (`TemplateResponse`).
- **htmx** loaded from CDN — no local copy, no npm, no bundler.
- **Tailwind CSS** loaded from CDN Play CDN for development; pin to a specific CDN version
  in production (never `latest`).
- **No TypeScript, no React, no Vue, no build pipeline.** If a feature genuinely requires
  client-side state complexity beyond htmx, open a discussion before writing JS.

## Interaction Model

- Every interactive element (button, form, link that triggers a server action) must use
  `hx-*` attributes — never raw `fetch()`, `XMLHttpRequest`, or inline `onclick` handlers.
- Common pattern:
  ```html
  <button hx-post="/admin/orders/{{ order.id }}/approve"
          hx-target="#order-row-{{ order.id }}"
          hx-swap="outerHTML">
    Approve
  </button>
  ```
- Use `hx-indicator` with a spinner element for all requests that may take > 200 ms.
- Prefer `hx-boost` on internal navigation links to avoid full-page reloads.

## Confirmation Modals

A **confirmation modal** is **required** before any of the following actions complete:

| Action | Modal must state |
|--------|-----------------|
| Any SQL write (INSERT/UPDATE/DELETE via admin UI) | Table name + operation + row count if known |
| Service restart (`tb restart <svc>`) | Service name + current status |
| Order approve / reject | Order ID + side + quantity + instrument |
| Proposal approve / reject | Proposal ID + description + submitter |

Implementation: use a shared `_confirm_modal.html` partial included in `base.html`.
The triggering button sets `hx-confirm` for simple cases; the modal partial handles complex ones.
Never bypass the modal with JavaScript.

## Template Structure

```
services/admin_service/templates/
├── base.html              # Layout, nav, modal partial includes
├── _confirm_modal.html    # Reusable confirmation modal
├── _flash.html            # Flash message partial
├── components/            # Reusable htmx partials (table rows, status badges, etc.)
└── pages/                 # Full-page templates (one per route group)
```

## Accessibility & Security

- All form inputs must have a `<label for="">` or `aria-label`.
- CSRF: FastAPI middleware provides a CSRF token; every mutating form must include
  `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`.
- Never render user-supplied strings unescaped — always use `{{ var }}`, never `{{ var | safe }}`
  unless the value is explicitly HTML generated server-side.
- No secrets, API keys, or internal IDs exposed in HTML source or JS variables.
