# Remediation pass — 2026-06-15

One-shot remediation of TheEyeBeta2025Live (run on `claude-opus-4-8`). Each numbered item is
a separate commit. Host-only systemd/DB state changes are recorded here because they leave no
other repo artifact. Constraint honored throughout: `public.*` not touched (deprecating);
`iam.*` read-only.

## P3 — cleanup

### [6] API supervision drift — `theeyebeta-api.service` masked

- The live external API runs as the **user** unit `theeyebeta-dataapi.service` (gunicorn, `:7000`).
- The system unit `theeyebeta-api.service` was disabled/dead and redundant.
- The host-only unit file was archived to `deploy/systemd/archived/theeyebeta-api.service`,
  removed from `/etc/systemd/system`, then `systemctl mask`ed (the path had to be freed first —
  it was a real file, not a `/usr/lib` shadow).
- Result: `is-enabled=masked`, `is-active=inactive`; `:7000` still served by `dataapi`.
- Reversible: `sudo systemctl unmask theeyebeta-api.service` + restore the archived file.
